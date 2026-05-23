"""FT + Original の真のlogitアンサンブル (同品質モデル合議)"""
import sys, numpy as np, json, time
from pathlib import Path
CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT)); sys.path.insert(0, str(CHORDMINI_ROOT/"src"))
import torch, mir_eval

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")

def get_tracks(n=180):
    t = []
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab.stem}.wav"
            if wav.exists(): t.append({"ref": str(lab), "audio": str(wav), "title": lab.stem})
    return t[:n]

def load_b(ckpt, mt='BTC'):
    from src.utils.hparams import HParams; from src.models import load_model
    from src.evaluation.utils.common import extract_norm_stats, extract_vocab
    from src.utils.device import get_device
    c = HParams.load(str(CHORDMINI_ROOT/'config'/'ChordMini.yaml'))
    d = get_device(); a = type('A',(),{'seq_len':None,'model_type':mt})()
    m,_,_ = load_model(str(ckpt),mt,c,d,a)
    mn,st = extract_norm_stats(str(ckpt)); i2c,c2i = extract_vocab(str(ckpt))
    m.eval()
    return {'model':m,'config':c,'mean':mn,'std':st,'idx_to_chord':i2c,'chord_to_idx':c2i,'device':d,'model_type':mt}

def get_logits(bundle, audio_path):
    from src.evaluation.utils.common import extract_song_features
    fm, fd = extract_song_features(audio_path, bundle['config'])
    fm = np.asarray(fm, dtype=np.float32)
    n = fm.shape[0]; sl = 108; nc = len(bundle['chord_to_idx'])
    dev = next(bundle['model'].parameters()).device
    mean = torch.as_tensor(bundle['mean'],dtype=torch.float32,device=dev)
    std = torch.as_tensor(bundle['std'],dtype=torch.float32,device=dev)
    rem = n % sl; pad = 0 if rem==0 else sl-rem
    if pad>0: fm = np.pad(fm,((0,pad),(0,0)),mode='constant')
    stride = max(1,int(sl*0.5)); pf = fm.shape[0]
    nw = max(1,((pf-sl)//stride)+1)
    ls = np.zeros((n,nc),dtype=np.float32); ct = np.zeros(n,dtype=np.int32)
    with torch.no_grad():
        bundle['model'].eval()
        for i in range(0,nw,16):
            batch,metas = [],[]
            for j in range(i,min(i+16,nw)):
                s=stride*j; e=s+sl
                if e>pf: continue
                v=min(sl,max(0,n-s))
                if v<=0: continue
                batch.append(fm[s:e]); metas.append((s,v))
            if not batch: continue
            t = torch.from_numpy(np.stack(batch)).float().to(dev)
            t = (t-mean)/(std+1e-8)
            out = bundle['model'](t)
            lo = (out[0] if isinstance(out,tuple) else out).detach().cpu().numpy()
            for k,(s,v) in enumerate(metas):
                ls[s:s+v] += lo[k,:v]; ct[s:s+v] += 1
    mask=ct>0; ls[mask]/=ct[mask,None]
    return ls, fd

def ens_predict(bundles, audio, weights):
    all_l = []; fd = None
    for b,w in zip(bundles,weights):
        l,f = get_logits(b, audio); all_l.append((l,w))
        if fd is None: fd=f
    mn = min(l.shape[0] for l,_ in all_l); nc = all_l[0][0].shape[1]
    comb = np.zeros((mn,nc),dtype=np.float32)
    for l,w in all_l: comb += l[:mn]*w
    preds = np.argmax(comb, axis=1)
    i2c = bundles[0]['idx_to_chord']
    iv = []; lb = []; prev=None; start=0.0
    for i,idx in enumerate(preds):
        ch=i2c.get(int(idx),'N'); t=float(i)*fd
        if prev is None: prev=ch; continue
        if ch!=prev: iv.append([start,t]); lb.append(prev); start=t; prev=ch
    if prev: iv.append([start,float(mn)*fd]); lb.append(prev)
    return np.array(iv), lb

def ev(bundles, tracks, weights, label):
    s = []
    for i,t in enumerate(tracks):
        try:
            ri,rl = mir_eval.io.load_labeled_intervals(t['ref'])
            pi,pl = ens_predict(bundles, t['audio'], weights)
            r = mir_eval.chord.evaluate(ri,rl,pi,pl)
            s.append(float(r['thirds']))
        except: pass
        if (i+1)%30==0: print(f"  [{label}] {i+1}/{len(tracks)}: {np.mean(s):.4f}")
    return np.mean(s) if s else 0

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tracks = get_tracks(180)
    
    print("Loading Original + FT + ChordNet...")
    orig = load_b(CHORDMINI_ROOT/"checkpoints"/"btc_model_best.pth")
    ft = load_b(CHORDMINI_ROOT/"checkpoints"/"beatles_ft"/"single_split"/"best_model.pth")
    cn = load_b(CHORDMINI_ROOT/"checkpoints"/"2e1d_model_best.pth", "ChordNet")
    print("All loaded.\n")
    
    configs = [
        ("Original only",        [orig],         [1.0]),
        ("FT only",              [ft],            [1.0]),
        ("Orig+FT 1:1",         [orig, ft],      [1.0, 1.0]),
        ("Orig+FT 2:1",         [orig, ft],      [2.0, 1.0]),
        ("Orig+FT 1:2",         [orig, ft],      [1.0, 2.0]),
        ("Orig+FT+CN 2:1:0.5",  [orig, ft, cn],  [2.0, 1.0, 0.5]),
        ("Orig+FT+CN 1:1:0.5",  [orig, ft, cn],  [1.0, 1.0, 0.5]),
    ]
    
    results = {}
    best_score, best_name = 0, ""
    
    for name, bundles, weights in configs:
        print(f"\n--- {name} ---")
        score = ev(bundles, tracks, weights, name[:10])
        results[name] = round(score, 4)
        marker = " *** BEST ***" if score > best_score else ""
        if score > best_score: best_score, best_name = score, name
        print(f"  {name}: {score:.4f}{marker}")
    
    print(f"\n{'='*70}")
    print(f"BEST: {best_name} = {best_score:.4f}")
    print(f"{'='*70}")
    
    with open(Path(r"D:\Music\nextchord\evaluation\ensemble_ft_results.json"),"w") as f:
        json.dump(results, f, indent=2)

if __name__=="__main__":
    main()
