import numpy as np
import scipy.io.wavfile as wavfile
import os

def generate_waveform(wav_path, n_points=2000):
    """
    Reads a WAV file and returns a list of normalized peak values (0.0 to 1.0)
    resampled to exactly n_points.
    """
    try:
        # Check file exists
        if not os.path.exists(wav_path):
            return []

        # Read WAV
        fs, data = wavfile.read(wav_path)
        
        # Handle empty/short files
        if len(data) == 0:
            return []
            
        # Convert to Mono if stereo
        if data.ndim > 1:
            # Average channels
            data = data.mean(axis=1)
        
        # Ensure we have enough data
        total_samples = len(data)
        if total_samples < n_points:
            # Upsample? Or just return raw
            step = 1
            n_points = total_samples 
        else:
            step = total_samples // n_points

        # Efficient downsampling using striding or reshaping
        # Reshape to (n_points, samples_per_point) and take max abs
        # Note: total_samples might not be perfectly divisible
        
        # Simple slicing method (fastest)
        # downsampled = data[::step][:n_points]
        
        # Better method: Max value per chunk (visual peak)
        # Truncate to make divisible
        samples_per_chunk = total_samples // n_points
        trunc_len = samples_per_chunk * n_points
        
        reshaped = data[:trunc_len].reshape(n_points, samples_per_chunk)
        
        # Calculate max amplitude per chunk (absolute)
        peaks = np.max(np.abs(reshaped), axis=1)
        
        # Normalize to 1.0
        max_val = np.max(peaks)
        if max_val > 0:
            normalized = peaks / max_val
        else:
            normalized = peaks
            
        return normalized.tolist()
        
    except Exception as e:
        print(f"Error extracting waveform: {e}")
        return []


from functools import lru_cache
import librosa
import time as _time

@lru_cache(maxsize=16)
def load_audio_cached(audio_path, sr=22050, mono=True):
    """
    スレッド間共有のLRUキャッシュ付き音声ロード。
    デコード結果をメモリ上に保持し、重複ロード時のI/Oおよびデコード処理時間を0秒にする。
    """
    t0 = _time.time()
    path_str = str(audio_path)
    y, sr_out = librosa.load(path_str, sr=sr, mono=mono)
    elapsed = _time.time() - t0
    print(f"[waveform_utils] load_audio_cached: Loaded {path_str} at sr={sr} in {elapsed:.2f}s (new load)")
    return y, sr_out
