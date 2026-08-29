import io
import json
import math
import random
import re
import zipfile
from collections import OrderedDict
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.optimize import linear_sum_assignment
from scipy.spatial import Delaunay
from sklearn.cluster import DBSCAN
from torch.utils.data import Dataset


def seed_everything(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic=True
    torch.backends.cudnn.benchmark=False


def file_key(name):
    stem=Path(name).stem.lower()
    nums=re.findall(r"\d+",stem)
    return str(int(nums[-1])) if nums else re.sub(r"[^a-z0-9]","",stem)


def archive_inventory(root):
    rows=[]
    for path in sorted(Path(root).rglob("*.zip")):
        with zipfile.ZipFile(path) as z:
            names=[x for x in z.namelist() if not x.endswith("/")]
        rows.append({"path":str(path),"xyz":sum(Path(x).suffix.lower()==".xyz" for x in names),"obj":sum(Path(x).suffix.lower()==".obj" for x in names),"files":len(names)})
    return pd.DataFrame(rows)


def choose_archives(table):
    if table.empty:
        raise FileNotFoundError("No Building3D ZIP archives were found")
    roof=table[(table.xyz>0)&(table.obj>0)]
    if roof.empty:
        roof=table[table.path.str.lower().str.contains("roof")&(table.xyz>0)]
    if roof.empty:
        raise FileNotFoundError("The roof point-cloud and wireframe archive was not found")
    roof_path=Path(roof.sort_values(["obj","xyz"],ascending=False).iloc[0].path)
    building=table[(table.xyz>0)&(table.path!=str(roof_path))]
    building_path=None if building.empty else Path(building.sort_values("xyz",ascending=False).iloc[0].path)
    return roof_path,building_path


def read_id_list(path):
    try:
        text=path.read_text(errors="ignore").strip()
    except Exception:
        return []
    if not text:
        return []
    if path.suffix.lower()==".json":
        try:
            data=json.loads(text)
        except Exception:
            return []
        if isinstance(data,dict):
            for key in ["ids","building_ids","buildings"]:
                if key in data:
                    return [str(x) for x in data[key]]
            values=list(data.values())
            return [str(x) for x in values[0]] if values else []
        if isinstance(data,list):
            return [str(x) for x in data]
        return []
    lines=text.splitlines()
    if not lines:
        return []
    first_line=lines[0]
    if "," in first_line:
        try:
            frame=pd.read_csv(path)
            cols={str(c).lower():c for c in frame.columns}
            id_col=next((cols[c] for c in ["building_id","buildingid","id","sample_id"] if c in cols),frame.columns[0])
            return frame[id_col].astype(str).tolist()
        except Exception:
            pass
    return [line.strip() for line in lines if line.strip()]


def find_split_manifest(root):
    root=Path(root)
    choices=[]
    for path in root.rglob("*.csv"):
        try:
            frame=pd.read_csv(path,nrows=20)
        except Exception:
            continue
        cols={str(x).lower():x for x in frame.columns}
        id_col=next((cols[x] for x in ["building_id","buildingid","id","sample_id"] if x in cols),None)
        split_col=next((cols[x] for x in ["split","subset","partition"] if x in cols),None)
        if id_col is not None and split_col is not None:
            choices.append((path,id_col,split_col))
    if choices:
        path,id_col,split_col=max(choices,key=lambda x:x[0].stat().st_size)
        frame=pd.read_csv(path)
        frame=frame.rename(columns={id_col:"building_id",split_col:"split"})
        frame["building_id"]=frame.building_id.map(lambda x:file_key(str(x)))
        frame["split"]=frame.split.astype(str).str.lower().replace({"validation":"val","valid":"val"})
        valid_cols=[x for x in frame.columns if "structural_valid" in str(x).lower() or str(x).lower()=="valid"]
        for col in valid_cols:
            flag=frame[col].astype(str).str.lower().isin(["true","1","yes"])
            frame=frame[flag]
        frame=frame[frame.split.isin(["train","val","test"])]
        return path,frame.drop_duplicates("building_id")

    split_files={}
    aliases={"train":[r"\btrain\b"],"val":[r"\bval\b",r"\bvalidation\b",r"\bvalid\b"],"test":[r"\btest\b"]}
    candidates=[]
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in [".txt",".json",".csv",".list"]:
            continue
        stem=path.stem.lower()
        if "id" in stem and "invalid" not in stem and "manifest" not in stem and "quality" not in stem:
            candidates.append(path)
    for split_name,patterns in aliases.items():
        for path in sorted(candidates):
            stem=re.sub(r"[^a-z]+"," ",path.stem.lower())
            if any(re.search(p,stem) for p in patterns):
                split_files.setdefault(split_name,path)

    print("id_candidate_files",[str(x) for x in candidates])
    print("split_files_matched",{k:str(v) for k,v in split_files.items()})

    if len(split_files)<2:
        raise FileNotFoundError(f"No Phase 1B CSV with building ID and split columns was found, and fewer than two split ID-list files were matched. Candidates seen: {[str(x) for x in candidates]}")

    rows=[]
    for split_name,path in split_files.items():
        ids=read_id_list(path)
        print(split_name,str(path),"count",len(ids))
        for building_id in ids:
            rows.append({"building_id":file_key(str(building_id)),"split":split_name})

    frame=pd.DataFrame(rows).drop_duplicates("building_id")
    if frame.empty:
        raise FileNotFoundError("Split ID-list files were found but contained no usable building IDs")

    quality_paths=list(root.rglob("*quality*.csv"))+[p for p in root.rglob("*manifest*.csv") if "structural" in p.stem.lower() or p.stem.lower()=="manifest_all"]
    for qpath in quality_paths:
        try:
            qframe=pd.read_csv(qpath)
        except Exception:
            continue
        qcols={str(c).lower():c for c in qframe.columns}
        id_col=next((qcols[c] for c in ["building_id","buildingid","id","sample_id"] if c in qcols),None)
        valid_col=next((qcols[c] for c in qcols if "structural_valid" in c or c=="valid"),None)
        if id_col is not None and valid_col is not None:
            qframe=qframe.rename(columns={id_col:"building_id"})
            qframe["building_id"]=qframe.building_id.map(lambda x:file_key(str(x)))
            flag=qframe[valid_col].astype(str).str.lower().isin(["true","1","yes"])
            valid_ids=set(qframe.loc[flag,"building_id"])
            frame=frame[frame.building_id.isin(valid_ids)]
            break

    manifest_path=next(iter(split_files.values())).parent
    return manifest_path,frame


def member_map(zf,suffix):
    out={}
    for name in zf.namelist():
        if Path(name).suffix.lower()==suffix:
            out[file_key(name)]=name
    return out


def read_xyz(zf,name):
    with zf.open(name) as f:
        raw=np.loadtxt(f,dtype=np.float64)
    if raw.ndim==1:
        raw=raw[None]
    raw=raw[np.isfinite(raw).all(1)]
    if raw.shape[1]<3:
        raise ValueError(name)
    return raw


def read_wireframe(zf,name):
    vertices=[]
    edges=[]
    with zf.open(name) as f:
        for raw in f:
            line=raw.decode("utf-8",errors="ignore").strip().split()
            if len(line)>=4 and line[0]=="v":
                vertices.append([float(line[1]),float(line[2]),float(line[3])])
            elif len(line)>=3 and line[0]=="l":
                chain=[int(x)-1 for x in line[1:]]
                edges.extend(zip(chain[:-1],chain[1:]))
    vertices=np.asarray(vertices,dtype=np.float64)
    edges=np.asarray(edges,dtype=np.int64).reshape(-1,2)
    keep=(edges>=0).all(1)&(edges<len(vertices)).all(1) if len(edges) else np.zeros(0,dtype=bool)
    return vertices,edges[keep]


def sample_points(raw,count,rng):
    replace=len(raw)<count
    ids=rng.choice(len(raw),count,replace=replace)
    return raw[ids]


def normalize_sample(raw,corners,count,rng):
    xyz=raw[:,:3]
    joined=np.vstack([xyz,corners])
    low=joined.min(0)
    high=joined.max(0)
    center=(low+high)/2
    scale=np.linalg.norm(joined-center,axis=1).max()
    scale=max(float(scale),1e-6)
    chosen=sample_points(raw,count,rng)
    xyz_norm=(chosen[:,:3]-center)/scale
    attrs=chosen[:,3:8]
    if attrs.shape[1]<5:
        attrs=np.pad(attrs,((0,0),(0,5-attrs.shape[1])))
    attrs=attrs.astype(np.float64)
    if attrs.shape[1]>=3:
        rgb=attrs[:,:3]
        attrs[:,:3]=np.clip(rgb/(255 if np.nanmax(rgb)>1.5 else 1),0,1)
    for col in range(3,5):
        lo=np.percentile(attrs[:,col],1)
        hi=np.percentile(attrs[:,col],99)
        attrs[:,col]=np.clip((attrs[:,col]-lo)/(hi-lo+1e-8),0,1)
    points=np.concatenate([xyz_norm,attrs],1).astype(np.float32)
    corner_norm=((corners-center)/scale).astype(np.float32)
    return points,corner_norm,center.astype(np.float64),scale


def build_cache(source_root,cache_root,point_count=2048,max_corners=64,max_edges=128,shard_size=256,seed=42):
    source_root=Path(source_root)
    cache_root=Path(cache_root)
    cache_root.mkdir(parents=True,exist_ok=True)
    table=archive_inventory(source_root)
    roof_path,building_path=choose_archives(table)
    manifest_path,manifest=find_split_manifest(source_root)
    rejected=[]
    index_rows=[]
    buffer=[]
    shard_no=0
    with zipfile.ZipFile(roof_path) as roof_zip:
        cloud_map=member_map(roof_zip,".xyz")
        wire_map=member_map(roof_zip,".obj")
        usable=manifest[manifest.building_id.isin(set(cloud_map)&set(wire_map))]
        for order,row in enumerate(usable.itertuples(index=False)):
            key=str(row.building_id)
            try:
                raw=read_xyz(roof_zip,cloud_map[key])
                corners,edges=read_wireframe(roof_zip,wire_map[key])
                if len(raw)<16 or len(corners)<4 or len(corners)>max_corners or len(edges)<4 or len(edges)>max_edges:
                    rejected.append({"building_id":key,"reason":"shape_limit"})
                    continue
                if not np.isfinite(corners).all():
                    rejected.append({"building_id":key,"reason":"nonfinite_corner"})
                    continue
                rng=np.random.default_rng(seed+order)
                points,corner_norm,center,scale=normalize_sample(raw,corners,point_count,rng)
                corner_pad=np.zeros((max_corners,3),dtype=np.float32)
                edge_pad=np.full((max_edges,2),-1,dtype=np.int16)
                corner_pad[:len(corner_norm)]=corner_norm
                edge_pad[:len(edges)]=edges.astype(np.int16)
                buffer.append({"building_id":key,"split":str(row.split),"points":torch.from_numpy(points),"corners":torch.from_numpy(corner_pad),"corner_count":len(corners),"edges":torch.from_numpy(edge_pad),"edge_count":len(edges),"center":torch.from_numpy(center),"scale":scale})
                if len(buffer)==shard_size:
                    name=f"shard_{shard_no:04d}.pt"
                    torch.save(buffer,cache_root/name)
                    for pos,item in enumerate(buffer):
                        index_rows.append({"building_id":item["building_id"],"split":item["split"],"shard":name,"row":pos,"scale":item["scale"]})
                    buffer=[]
                    shard_no+=1
            except Exception as error:
                rejected.append({"building_id":key,"reason":type(error).__name__})
    if buffer:
        name=f"shard_{shard_no:04d}.pt"
        torch.save(buffer,cache_root/name)
        for pos,item in enumerate(buffer):
            index_rows.append({"building_id":item["building_id"],"split":item["split"],"shard":name,"row":pos,"scale":item["scale"]})
    index=pd.DataFrame(index_rows)
    reject_frame=pd.DataFrame(rejected)
    index.to_csv(cache_root/"index.csv",index=False)
    reject_frame.to_csv(cache_root/"rejected.csv",index=False)
    config={"source_root":str(source_root),"roof_archive":str(roof_path),"building_archive":None if building_path is None else str(building_path),"manifest":str(manifest_path),"point_count":point_count,"max_corners":max_corners,"max_edges":max_edges,"seed":seed,"samples":len(index),"splits":index.split.value_counts().to_dict()}
    (cache_root/"cache_config.json").write_text(json.dumps(config,indent=2))
    return table,index,reject_frame,config


class RoofDataset(Dataset):
    def __init__(self,cache_root,split,augment=False,cache_size=4):
        self.root=Path(cache_root)
        frame=pd.read_csv(self.root/"index.csv")
        self.frame=frame[frame.split==split].reset_index(drop=True)
        self.augment=augment
        self.cache_size=cache_size
        self.cache=OrderedDict()

    def __len__(self):
        return len(self.frame)

    def load_shard(self,name):
        if name in self.cache:
            self.cache.move_to_end(name)
            return self.cache[name]
        data=torch.load(self.root/name,map_location="cpu",weights_only=False)
        self.cache[name]=data
        if len(self.cache)>self.cache_size:
            self.cache.popitem(last=False)
        return data

    def __getitem__(self,index):
        row=self.frame.iloc[index]
        item=self.load_shard(row.shard)[int(row.row)]
        points=item["points"].clone().float()
        corners=item["corners"].clone().float()
        n=int(item["corner_count"])
        if self.augment:
            angle=(torch.rand(1).item()*2-1)*math.pi
            c=math.cos(angle)
            s=math.sin(angle)
            rot=torch.tensor([[c,-s,0],[s,c,0],[0,0,1]],dtype=torch.float32)
            points[:,:3]=points[:,:3]@rot.T
            corners[:n]=corners[:n]@rot.T
            if torch.rand(1).item()<0.5:
                points[:,0]*=-1
                corners[:n,0]*=-1
            points[:,:3]+=torch.randn_like(points[:,:3])*0.003
        return {"building_id":item["building_id"],"points":points,"corners":corners,"corner_count":torch.tensor(n),"edges":item["edges"].clone().long(),"edge_count":torch.tensor(int(item["edge_count"])),"center":item["center"].clone().double(),"scale":torch.tensor(float(item["scale"]),dtype=torch.float32)}


def square_distance(src,dst):
    return torch.sum(src**2,-1,keepdim=True)+torch.sum(dst**2,-1).unsqueeze(1)-2*torch.matmul(src,dst.transpose(1,2))


def index_points(points,idx):
    batch=torch.arange(points.shape[0],device=points.device).view(-1,*([1]*(idx.ndim-1))).expand_as(idx)
    return points[batch,idx]


def farthest_point_sample(xyz,npoint):
    b,n,_=xyz.shape
    centroids=torch.zeros(b,npoint,dtype=torch.long,device=xyz.device)
    distance=torch.full((b,n),1e10,device=xyz.device)
    farthest=torch.randint(0,n,(b,),device=xyz.device)
    batch=torch.arange(b,device=xyz.device)
    for i in range(npoint):
        centroids[:,i]=farthest
        centroid=xyz[batch,farthest].view(b,1,3)
        dist=torch.sum((xyz-centroid)**2,-1)
        distance=torch.minimum(distance,dist)
        farthest=torch.max(distance,-1).indices
    return centroids


def query_neighbors(radius,nsample,xyz,new_xyz):
    dist=square_distance(new_xyz,xyz)
    idx=dist.argsort(-1)[:,:,:nsample]
    picked=torch.gather(dist,2,idx)
    first=idx[:,:,0:1].expand_as(idx)
    idx=torch.where(picked<=radius*radius,idx,first)
    return idx


class SetAbstraction(nn.Module):
    def __init__(self,npoint,radius,nsample,in_channel,mlp):
        super().__init__()
        self.npoint=npoint
        self.radius=radius
        self.nsample=nsample
        layers=[]
        last=in_channel+3
        for out in mlp:
            layers.extend([nn.Conv2d(last,out,1,bias=False),nn.BatchNorm2d(out),nn.ReLU(inplace=True)])
            last=out
        self.net=nn.Sequential(*layers)

    def forward(self,xyz,features):
        ids=farthest_point_sample(xyz,self.npoint)
        new_xyz=index_points(xyz,ids)
        group_ids=query_neighbors(self.radius,self.nsample,xyz,new_xyz)
        grouped_xyz=index_points(xyz,group_ids)-new_xyz.unsqueeze(2)
        if features is None:
            grouped=grouped_xyz
        else:
            grouped=torch.cat([grouped_xyz,index_points(features,group_ids)],-1)
        grouped=self.net(grouped.permute(0,3,2,1))
        return new_xyz,torch.max(grouped,2).values.permute(0,2,1)


class FeaturePropagation(nn.Module):
    def __init__(self,in_channel,mlp):
        super().__init__()
        layers=[]
        last=in_channel
        for out in mlp:
            layers.extend([nn.Conv1d(last,out,1,bias=False),nn.BatchNorm1d(out),nn.ReLU(inplace=True)])
            last=out
        self.net=nn.Sequential(*layers)

    def forward(self,xyz1,xyz2,feat1,feat2):
        if xyz2.shape[1]==1:
            interp=feat2.repeat(1,xyz1.shape[1],1)
        else:
            dist,idx=square_distance(xyz1,xyz2).topk(3,largest=False)
            weight=1/(dist+1e-8)
            weight=weight/weight.sum(-1,keepdim=True)
            interp=(index_points(feat2,idx)*weight.unsqueeze(-1)).sum(2)
        merged=interp if feat1 is None else torch.cat([feat1,interp],-1)
        return self.net(merged.permute(0,2,1)).permute(0,2,1)


class CornerPointNet2(nn.Module):
    def __init__(self,extra_channels=5):
        super().__init__()
        self.sa1=SetAbstraction(512,0.12,32,extra_channels,[64,64,128])
        self.sa2=SetAbstraction(128,0.28,48,128,[128,128,256])
        self.sa3=SetAbstraction(32,0.55,64,256,[256,256,512])
        self.fp3=FeaturePropagation(768,[256,256])
        self.fp2=FeaturePropagation(384,[256,128])
        self.fp1=FeaturePropagation(128+extra_channels,[128,128,128])
        self.shared=nn.Sequential(nn.Conv1d(128,128,1,bias=False),nn.BatchNorm1d(128),nn.ReLU(inplace=True))
        self.corner_head=nn.Conv1d(128,1,1)
        self.offset_head=nn.Conv1d(128,3,1)

    def forward(self,points):
        xyz=points[:,:,:3]
        feat=points[:,:,3:]
        xyz1,feat1=self.sa1(xyz,feat)
        xyz2,feat2=self.sa2(xyz1,feat1)
        xyz3,feat3=self.sa3(xyz2,feat2)
        feat2=self.fp3(xyz2,xyz3,feat2,feat3)
        feat1=self.fp2(xyz1,xyz2,feat1,feat2)
        feat0=self.fp1(xyz,xyz1,feat,feat1)
        shared=self.shared(feat0.permute(0,2,1)).permute(0,2,1)
        return self.corner_head(shared.permute(0,2,1)).squeeze(1),self.offset_head(shared.permute(0,2,1)).permute(0,2,1),shared


def corner_targets(points,corners,counts,scales,radius_m=0.35):
    labels=[]
    offsets=[]
    for i in range(len(points)):
        truth=corners[i,:int(counts[i])]
        dist=square_distance(points[i:i+1,:,:3],truth[None]).squeeze(0)
        nearest=dist.argmin(1)
        radius=radius_m/scales[i]
        label=(dist[torch.arange(len(points[i]),device=points.device),nearest].sqrt()<=radius).float()
        offset=(truth[nearest]-points[i,:,:3])/radius
        labels.append(label)
        offsets.append(offset)
    return torch.stack(labels),torch.stack(offsets)


def focal_binary(logits,targets,alpha=0.75,gamma=2.0):
    prob=torch.sigmoid(logits)
    ce=F.binary_cross_entropy_with_logits(logits,targets,reduction="none")
    pt=prob*targets+(1-prob)*(1-targets)
    weight=alpha*targets+(1-alpha)*(1-targets)
    return (weight*(1-pt).pow(gamma)*ce).mean()


def corner_loss(logits,offsets,pred_offsets,labels):
    cls=focal_binary(logits,labels)
    mask=labels.bool()
    reg=F.smooth_l1_loss(pred_offsets[mask],offsets[mask]) if mask.any() else pred_offsets.sum()*0
    return cls+reg,cls.detach(),reg.detach()


def predict_corners(points,logits,offsets,scale,score_thresh=0.5,radius_m=0.35,cluster_m=0.25,min_samples=2,max_corners=64):
    scores=torch.sigmoid(logits).detach().cpu().numpy()
    xyz=points[:,:3].detach().cpu().numpy()
    delta=offsets.detach().cpu().numpy()
    keep=np.flatnonzero(scores>=score_thresh)
    if len(keep)==0:
        keep=np.argsort(scores)[-4:]
    proposals=xyz[keep]+delta[keep]*(radius_m/float(scale))
    groups=DBSCAN(eps=cluster_m/float(scale),min_samples=min_samples).fit_predict(proposals)
    corners=[]
    confidence=[]
    for group in sorted(set(groups)):
        if group<0:
            continue
        mask=groups==group
        w=scores[keep][mask]
        corners.append(np.average(proposals[mask],axis=0,weights=w+1e-6))
        confidence.append(float(w.max()))
    if len(corners)<4:
        take=np.argsort(scores)[-4:]
        corners=list(xyz[take]+delta[take]*(radius_m/float(scale)))
        confidence=list(scores[take])
    order=np.argsort(confidence)[::-1][:max_corners]
    return np.asarray(corners,dtype=np.float32)[order],np.asarray(confidence,dtype=np.float32)[order]


def interpolate_features(points,features,corners):
    if len(corners)==0:
        return features.new_zeros((0,features.shape[-1]))
    query=torch.as_tensor(corners,dtype=points.dtype,device=points.device)[None]
    dist,idx=square_distance(query,points[None,:,:3]).topk(3,largest=False)
    weight=1/(dist+1e-8)
    weight=weight/weight.sum(-1,keepdim=True)
    return (index_points(features[None],idx)*weight.unsqueeze(-1)).sum(2).squeeze(0)


class EdgeGraphNet(nn.Module):
    def __init__(self,point_dim=128,node_dim=128):
        super().__init__()
        self.node_in=nn.Sequential(nn.Linear(point_dim+4,node_dim),nn.ReLU(),nn.Linear(node_dim,node_dim),nn.ReLU())
        self.update1=nn.Sequential(nn.Linear(node_dim*2,node_dim),nn.ReLU(),nn.Linear(node_dim,node_dim))
        self.update2=nn.Sequential(nn.Linear(node_dim*2,node_dim),nn.ReLU(),nn.Linear(node_dim,node_dim))
        self.edge_head=nn.Sequential(nn.Linear(node_dim*4+7,256),nn.ReLU(),nn.Dropout(0.2),nn.Linear(256,128),nn.ReLU(),nn.Linear(128,1))

    def forward(self,corner_xyz,corner_scores,point_features):
        node=self.node_in(torch.cat([point_features,corner_xyz,corner_scores[:,None]],1))
        for update in [self.update1,self.update2]:
            global_node=node.max(0,keepdim=True).values.expand_as(node)
            node=node+update(torch.cat([node,global_node],1))
        pairs=torch.combinations(torch.arange(len(node),device=node.device),r=2)
        left=node[pairs[:,0]]
        right=node[pairs[:,1]]
        a=corner_xyz[pairs[:,0]]
        b=corner_xyz[pairs[:,1]]
        geom=torch.cat([a,b,torch.norm(a-b,dim=1,keepdim=True)],1)
        edge_feat=torch.cat([left,right,torch.abs(left-right),left*right,geom],1)
        return pairs,self.edge_head(edge_feat).squeeze(1)


def edge_labels(pairs,edges,count):
    truth={tuple(sorted(map(int,x))) for x in edges[:count].tolist()}
    return torch.tensor([float(tuple(sorted(map(int,x))) in truth) for x in pairs.detach().cpu().tolist()],device=pairs.device)


def match_corners(pred,truth,tolerance_m):
    if len(pred)==0 or len(truth)==0:
        return {},0,0.0
    dist=np.linalg.norm(pred[:,None]-truth[None],axis=2)
    rows,cols=linear_sum_assignment(dist)
    mapping={int(r):int(c) for r,c in zip(rows,cols) if dist[r,c]<=tolerance_m}
    total=sum(dist[r,c] for r,c in mapping.items())
    return mapping,len(mapping),float(total)


def reconstruction_counts(pred_corners,pred_edges,truth_corners,truth_edges,tolerance_m=0.5):
    mapping,corner_tp,offset_sum=match_corners(pred_corners,truth_corners,tolerance_m)
    truth_set={tuple(sorted(map(int,x))) for x in truth_edges.tolist()}
    edge_tp=0
    for a,b in pred_edges:
        if int(a) in mapping and int(b) in mapping and tuple(sorted((mapping[int(a)],mapping[int(b)]))) in truth_set:
            edge_tp+=1
    return {"corner_tp":corner_tp,"corner_pred":len(pred_corners),"corner_true":len(truth_corners),"corner_offset_sum":offset_sum,"edge_tp":edge_tp,"edge_pred":len(pred_edges),"edge_true":len(truth_edges)}


def finalize_counts(rows):
    sums={key:sum(row[key] for row in rows) for key in rows[0]} if rows else {key:0 for key in ["corner_tp","corner_pred","corner_true","corner_offset_sum","edge_tp","edge_pred","edge_true"]}
    cp=sums["corner_tp"]/max(sums["corner_pred"],1)
    cr=sums["corner_tp"]/max(sums["corner_true"],1)
    ep=sums["edge_tp"]/max(sums["edge_pred"],1)
    er=sums["edge_tp"]/max(sums["edge_true"],1)
    return {"ACO":sums["corner_offset_sum"]/max(sums["corner_tp"],1),"CP":cp,"CR":cr,"C_F1":2*cp*cr/max(cp+cr,1e-8),"EP":ep,"ER":er,"E_F1":2*ep*er/max(ep+er,1e-8)}


def triangulate_cycle(vertices,cycle):
    pts=vertices[np.asarray(cycle)]
    center=pts.mean(0)
    _,_,vh=np.linalg.svd(pts-center,full_matrices=False)
    uv=(pts-center)@vh[:2].T
    try:
        tri=Delaunay(uv).simplices
    except Exception:
        return []
    return [[cycle[int(a)],cycle[int(b)],cycle[int(c)]] for a,b,c in tri]


def wireframe_to_mesh(vertices,edges,base_z):
    graph=nx.Graph()
    graph.add_edges_from([tuple(map(int,x)) for x in edges])
    roof_faces=[]
    for cycle in nx.cycle_basis(graph):
        if len(cycle)>=3:
            roof_faces.extend(triangulate_cycle(vertices,cycle))
    counts={}
    for face in roof_faces:
        for a,b in [(face[0],face[1]),(face[1],face[2]),(face[2],face[0])]:
            key=tuple(sorted((a,b)))
            counts[key]=counts.get(key,0)+1
    boundary=[edge for edge,count in counts.items() if count==1]
    n=len(vertices)
    bottom=vertices.copy()
    bottom[:,2]=base_z
    faces=[list(x) for x in roof_faces]
    for a,b in boundary:
        faces.extend([[a,b,b+n],[a,b+n,a+n]])
    boundary_graph=nx.Graph()
    boundary_graph.add_edges_from(boundary)
    for cycle in nx.cycle_basis(boundary_graph):
        for face in triangulate_cycle(bottom,cycle):
            faces.append([face[2]+n,face[1]+n,face[0]+n])
    return np.vstack([vertices,bottom]),np.asarray(faces,dtype=np.int64)


def write_obj(path,vertices,edges=None,faces=None):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w") as f:
        for x,y,z in vertices:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        if edges is not None:
            for a,b in edges:
                f.write(f"l {int(a)+1} {int(b)+1}\n")
        if faces is not None:
            for a,b,c in faces:
                f.write(f"f {int(a)+1} {int(b)+1} {int(c)+1}\n")
