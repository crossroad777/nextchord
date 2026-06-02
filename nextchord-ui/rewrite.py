import re

with open("src/hooks/useNextChord.js", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'const API_BASE = import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL : "http://localhost:8000";',
    '''export const getApiBase = () => {
  return localStorage.getItem('nextchord-api-base') || (import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL : "http://localhost:8000");
};'''
)

content = content.replace('${API_BASE}', '${getApiBase()}')

setlist_state = '''
  const [viewMode, setViewMode] = useState("text");

  // Setlist State
  const [setlistData, setSetlistData] = useState([]);
  const [setlistName, setSetlistName] = useState("");
'''
content = content.replace('  const [viewMode, setViewMode] = useState("text");', setlist_state)

setlist_func = '''
  const startSetlist = async (folderName, items) => {
    if (!items || items.length === 0) return;
    setStatus(STATUS.PROCESSING);
    setProgressMsg(`セットリストを構築中...`);
    
    try {
      const results = await Promise.all(items.map(async (item) => {
        const res = await fetch(`${getApiBase()}/result/${item.id}`);
        if (!res.ok) throw new Error(`Failed to load ${item.id}`);
        const data = await res.json();
        const historyItem = history.find(h => h.session_id === item.id) || {};
        return {
          id: item.id,
          result: data,
          filename: historyItem.filename || "Unknown",
          artist: historyItem.artist || "",
        };
      }));
      setSetlistData(results);
      setSetlistName(folderName);
      setStatus("setlist_view");
    } catch (e) {
      console.error(e);
      setStatus(STATUS.FAILED);
      setProgressMsg("セットリストの読み込みに失敗しました");
    }
  };

  const [ytUrl, setYtUrl] = useState("");
'''
content = content.replace('  const [ytUrl, setYtUrl] = useState("");', setlist_func)

content = content.replace('exportSettings, importSettings,', 'exportSettings, importSettings,\n    setlistData, setlistName, startSetlist,')

import_line = 'import { transposeChord } from "../utils/musicUtils";'
import_line_new = 'import { transposeChord, calculateBestCapo } from "../utils/musicUtils";'
content = content.replace(import_line, import_line_new)

capo_state = '''  const [capo, setCapo] = useState(0);
  const [recommendedCapo, setRecommendedCapo] = useState(0);'''
content = content.replace('  const [capo, setCapo] = useState(0);', capo_state)

load_capo = '''            const savedCapo = savedSettings.capo;
            if (savedCapo !== undefined) setCapo(savedCapo);
'''
load_capo_new = '''            const bestCapo = calculateBestCapo(data.chord_blocks || []);
            setRecommendedCapo(bestCapo);
            
            const savedCapo = savedSettings.capo;
            if (savedCapo !== undefined) {
              setCapo(savedCapo);
            } else {
              setCapo(bestCapo);
            }
'''
content = content.replace(load_capo, load_capo_new)

export_capo = '''    capo, setCapo: handleCapoChange,'''
export_capo_new = '''    capo, setCapo: handleCapoChange, recommendedCapo,'''
content = content.replace(export_capo, export_capo_new)

with open("src/hooks/useNextChord.js", "w", encoding="utf-8") as f:
    f.write(content)
