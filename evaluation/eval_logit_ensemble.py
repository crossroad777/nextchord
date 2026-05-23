"""Logit-level ensemble evaluation"""
import sys, numpy as np
from pathlib import Path
R = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "src"))
import torch, mir_eval
from src.utils.hparams import HParams
from src.models import load_model
from src.evaluation.utils.common import extract_norm_stats, extract_vocab, extract_song_features
from src.utils.device import get_device

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")
config = HParams.load(str(R / "config" / "ChordMini.yaml"))
device = get_device()

ckpts = {
    "Original": str(R / "checkpoints" / "btc_model_best.pth"),
    "FT": str(R / "checkpoints" / "beatles_ft" / "single_split" / "best_model.pth"),
    "Focal": str(R / "checkpoints" / "focal_ft" / "best_model.pth"),
}

loaded = {}
for name, ckpt in ckpts.items():
    args = type("A", (), {"seq_len": None, "model_type": "BTC"})()
    m, _, _ = load_model(ckpt, "BTC", config, device, args)
    mn, st = extract_norm_stats(ckpt)
    i2c, c2i = extract_vocab(ckpt)
    m.eval()
    loaded[name] = (m, mn, st, i2c, c2i)

def get_logits(model, fm, mn, st, n_classes, seq_len=108):
    feat = (fm - mn) / (st + 1e-8)
    n = feat.shape[0]
    stride = seq_len // 8
    all_logits = np.zeros((n, n_classes), dtype=np.float32)
    counts = np.zeros(n, dtype=np.float32)
    for start in range(0, max(1, n - seq_len + 1), stride):
        end = min(start + seq_len, n)
        chunk = feat[start:end]
        if chunk.shape[0] < seq_len:
            pad = np.zeros((seq_len - chunk.shape[0], chunk.shape[1]), dtype=np.float32)
            chunk = np.concatenate([chunk, pad])
        x = torch.from_numpy(chunk).unsqueeze(0).to(device)
        with torch.no_grad():
            out = model(x)
            logits = out[0] if isinstance(out, tuple) else out
        l = logits.cpu().numpy()[0]
        valid = min(end - start, seq_len)
        all_logits[start:start+valid] += l[:valid]
        counts[start:start+valid] += 1
    mask = counts > 0
    all_logits[mask] /= counts[mask, None]
    return all_logits

ref_i2c = loaded["FT"][3]
n_classes = len(loaded["FT"][4])

combos = {
    "FT_only": ["FT"],
    "FT+Orig": ["FT", "Original"],
    "FT+Focal": ["FT", "Focal"],
    "All3": ["FT", "Original", "Focal"],
}

scores = {k: [] for k in combos}
count = 0

for ad in sorted(ANNO.iterdir()):
    if not ad.is_dir(): continue
    for lab in sorted(ad.glob("*.lab")):
        wav = AUDIO / ad.name / f"{lab.stem}.wav"
        if not wav.exists(): continue
        count += 1
        try:
            ri, rl = mir_eval.io.load_labeled_intervals(str(lab))
            fm, fd = extract_song_features(str(wav), config)
            
            logits_all = {}
            for name, (m, mn, st, i2c, c2i) in loaded.items():
                logits_all[name] = get_logits(m, fm, mn, st, n_classes)
            
            for combo_name, model_list in combos.items():
                n_frames = min(l.shape[0] for l in logits_all.values())
                avg = np.zeros((n_frames, n_classes), dtype=np.float32)
                for mname in model_list:
                    avg += logits_all[mname][:n_frames]
                avg /= len(model_list)
                pred = avg.argmax(axis=1)
                
                iv = []; lb = []; prev = None; start = 0.0
                for ii, idx in enumerate(pred):
                    ch = ref_i2c.get(int(idx), "N"); t = float(ii) * fd
                    if prev is None: prev = ch; continue
                    if ch != prev:
                        iv.append([start, t]); lb.append(prev)
                        start = t; prev = ch
                if prev: iv.append([start, float(len(pred)) * fd]); lb.append(prev)
                r = mir_eval.chord.evaluate(ri, rl, np.array(iv), lb)
                scores[combo_name].append(float(r["thirds"]))
            
            if count % 30 == 0:
                print(f"{count} tracks:", flush=True)
                for k, v in scores.items():
                    print(f"  {k}: {np.mean(v):.4f}", flush=True)
        except:
            pass

print("=" * 60, flush=True)
print(f"Logit-Level Ensemble ({count} tracks)", flush=True)
print("=" * 60, flush=True)
for k, v in scores.items():
    print(f"  {k:12s}: {np.mean(v):.4f}", flush=True)
