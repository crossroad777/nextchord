import React, { useState, useRef } from "react";
import {
  Play, ChevronRight, ChevronDown, History, UploadCloud, Music,
  Star, FolderPlus, Folder, Trash2, Download, Upload, MoreVertical, Settings
} from 'lucide-react';

export function UploadView({
  fileInputRef,
  ytUrl,
  setYtUrl,
  handleYouTubeUpload,
  history,
  restoreSession,
  favorites = [],
  getFolders,
  getFavoritesByFolder,
  createFolder,
  deleteFolder,
  moveToFolder,
  exportSettings,
  importSettings,
  showToast,
  startSetlist,
  onOpenSettings,
}) {
  const [activeTab, setActiveTab] = useState('history');
  const [expandedFolders, setExpandedFolders] = useState({});
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [openMoveMenu, setOpenMoveMenu] = useState(null);
  const importInputRef = useRef(null);

  const toggleFolderExpand = (name) => {
    setExpandedFolders(prev => ({ ...prev, [name]: !prev[name] }));
  };

  const handleCreateFolder = () => {
    if (newFolderName.trim()) {
      createFolder(newFolderName.trim());
      setNewFolderName('');
      setShowNewFolder(false);
    }
  };

  const handleExport = () => {
    const json = exportSettings();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nextchord-settings-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    if (showToast) showToast('設定をエクスポートしました');
  };

  const handleImportFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      importSettings(ev.target.result);
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  // お気に入りの曲一覧（history からファイル名等を引く）
  const historyMap = {};
  history.forEach(h => { historyMap[h.session_id] = h; });

  const folders = getFolders ? getFolders() : [];
  const uncategorized = favorites.filter(x => !x.folder && !x.id.startsWith('__folder__'));

  const renderFavItem = (fav) => {
    const h = historyMap[fav.id];
    const allFolders = getFolders ? getFolders() : [];
    return (
      <div
        key={fav.id}
        className="flex items-center justify-between p-3.5 bg-[var(--nc-surface)] border border-[var(--nc-border)] rounded-xl hover:border-[rgba(99,102,241,0.2)] hover:bg-[var(--nc-surface-2)] transition-all cursor-pointer group"
      >
        <div
          className="flex items-center gap-3 flex-1 min-w-0"
          onClick={() => restoreSession(fav.id)}
        >
          <div className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-[11px] uppercase flex-shrink-0" style={{ background: 'var(--nc-primary-soft)', color: 'var(--nc-primary)' }}>
            {h?.key ? h.key.split(' ')[0] : '★'}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-[var(--nc-text)] text-sm truncate max-w-[200px]">{h?.filename || fav.id.slice(0, 12)}</div>
            <div className="text-[10px] text-[var(--nc-text-ghost)] font-medium">{h?.created_at || fav.id}</div>
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0 relative">
          <button
            onClick={(e) => { e.stopPropagation(); setOpenMoveMenu(openMoveMenu === fav.id ? null : fav.id); }}
            className="p-1.5 rounded-lg hover:bg-[var(--nc-surface-2)] transition-all text-[var(--nc-text-ghost)] hover:text-[var(--nc-text-secondary)]"
            title="フォルダに移動"
            aria-label="Move to folder"
          >
            <MoreVertical size={14} />
          </button>
          {openMoveMenu === fav.id && (
            <div
              className="absolute right-0 top-full mt-1 z-20 min-w-[140px] py-1 rounded-xl shadow-xl border border-[var(--nc-border)]"
              style={{ background: 'var(--nc-surface)' }}
            >
              <button
                onClick={(e) => { e.stopPropagation(); moveToFolder(fav.id, ''); setOpenMoveMenu(null); }}
                className="w-full text-left px-3 py-2 text-xs font-medium text-[var(--nc-text-secondary)] hover:bg-[var(--nc-surface-2)] transition-colors"
              >
                未分類
              </button>
              {allFolders.map(fn => (
                <button
                  key={fn}
                  onClick={(e) => { e.stopPropagation(); moveToFolder(fav.id, fn); setOpenMoveMenu(null); }}
                  className="w-full text-left px-3 py-2 text-xs font-medium text-[var(--nc-text-secondary)] hover:bg-[var(--nc-surface-2)] transition-colors flex items-center gap-2"
                >
                  <Folder size={12} /> {fn}
                </button>
              ))}
            </div>
          )}
          <ChevronRight size={16} className="text-[var(--nc-text-ghost)] group-hover:text-[var(--nc-primary)] group-hover:translate-x-0.5 transition-all" />
        </div>
      </div>
    );
  };

  const hasFavorites = favorites.filter(x => !x.id.startsWith('__folder__')).length > 0 || folders.length > 0;

  return (
    <div className="h-full flex flex-col items-center justify-start pt-16 p-12 text-center max-w-4xl mx-auto animate-in fade-in duration-1000 relative">
      {/* Subtle ambient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[300px] pointer-events-none" style={{ background: 'radial-gradient(ellipse, rgba(99, 102, 241, 0.06) 0%, transparent 70%)' }} />

      {/* Hero Logo */}
      <div className="nc-hero-logo-icon">
        <Music size={32} className="text-white" />
      </div>
      <h1 className="text-7xl font-black nc-logo-text-hero tracking-tighter mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>NextChord</h1>
      <p className="text-[var(--nc-text-secondary)] font-medium mb-16 text-lg leading-relaxed max-w-lg">
        音楽を構造で捉える。AIが楽曲を瞬時に解析。 <br />
        <span className="text-[var(--nc-text-muted)]">コード譜・TAB・五線譜・音源分離</span>
      </p>

      <div className="w-full max-w-md relative z-10">
        <div
          onClick={() => fileInputRef.current.click()}
          className="p-10 nc-card hover:border-[rgba(99,102,241,0.3)] transition-all cursor-pointer group text-center"
          role="button"
          aria-label="Select audio file to analyze"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current.click(); } }}
        >
          <div className="p-4 rounded-2xl w-fit mx-auto mb-5 group-hover:scale-110 transition-transform" style={{ background: 'var(--nc-primary-soft)', border: '1px solid rgba(99,102,241,0.12)' }}>
            <UploadCloud size={40} className="text-[var(--nc-primary)]" />
          </div>
          <h4 className="font-bold text-[var(--nc-text)] text-xl mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>音源をドラッグ＆ドロップ</h4>
          <p className="text-sm text-[var(--nc-text-muted)] mb-6">MP3, WAV, M4A または YouTubeリンク</p>
          <div className="nc-btn-primary inline-flex text-[11px] uppercase tracking-[0.15em] px-5 py-2.5">
            ファイルを選択
          </div>
        </div>

        {/* YouTube URL Input */}
        <div className="mt-6 flex items-center gap-3 text-[var(--nc-text-muted)]">
          <div className="flex-1 h-px bg-[var(--nc-border)]" />
          <span className="text-[10px] font-bold uppercase tracking-widest">または</span>
          <div className="flex-1 h-px bg-[var(--nc-border)]" />
        </div>
        <div className="mt-4 flex gap-2 items-center w-full">
          <div className="flex-1 relative">
            <input
              type="text"
              value={ytUrl}
              onChange={(e) => setYtUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && ytUrl.trim()) handleYouTubeUpload(ytUrl.trim()); }}
              placeholder="Paste YouTube URL"
              aria-label="YouTube URL input"
              className="w-full px-4 py-3 rounded-xl text-sm bg-[var(--nc-surface)] border border-[var(--nc-border)] text-[var(--nc-text)] placeholder-[var(--nc-text-muted)] focus:outline-none focus:border-[var(--nc-primary)] focus:ring-1 focus:ring-[var(--nc-primary)] transition-all"
              style={{ fontFamily: "'Inter', sans-serif" }}
            />
          </div>
          <button
            onClick={() => { if (ytUrl.trim()) handleYouTubeUpload(ytUrl.trim()); }}
            disabled={!ytUrl.trim()}
            className="px-5 py-3 rounded-xl text-sm font-bold transition-all flex items-center gap-2 flex-shrink-0"
            aria-label="Start YouTube analysis"
            style={{
              background: ytUrl.trim() ? 'linear-gradient(135deg, #ef4444, #dc2626)' : 'var(--nc-surface-2)',
              color: ytUrl.trim() ? '#fff' : 'var(--nc-text-muted)',
              border: ytUrl.trim() ? 'none' : '1px solid var(--nc-border)',
              cursor: ytUrl.trim() ? 'pointer' : 'not-allowed',
              opacity: ytUrl.trim() ? 1 : 0.6,
            }}
          >
            <Play size={14} fill="currentColor" />
            解析
          </button>
        </div>

        {/* Tab Switcher: 履歴 | お気に入り */}
        {(history.length > 0 || hasFavorites) && (
          <div className="mt-14 text-left">
            <div className="flex items-center gap-1 mb-5">
              <button
                onClick={() => setActiveTab('history')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all"
                style={{
                  background: activeTab === 'history' ? 'var(--nc-primary-soft)' : 'transparent',
                  color: activeTab === 'history' ? 'var(--nc-primary)' : 'var(--nc-text-muted)',
                }}
              >
                <History size={12} /> 履歴
              </button>
              <button
                onClick={() => setActiveTab('favorites')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all"
                style={{
                  background: activeTab === 'favorites' ? 'var(--nc-primary-soft)' : 'transparent',
                  color: activeTab === 'favorites' ? 'var(--nc-primary)' : 'var(--nc-text-muted)',
                }}
              >
                <Star size={12} /> お気に入り
              </button>

              <div className="ml-auto flex items-center gap-1">
                <button
                  onClick={onOpenSettings}
                  className="p-1.5 rounded-lg hover:bg-[var(--nc-surface-2)] transition-all text-[var(--nc-text-ghost)] hover:text-[var(--nc-text)]"
                  title="サーバー設定"
                  aria-label="Server Settings"
                >
                  <Settings size={16} />
                </button>
                <div className="w-px h-4 bg-[var(--nc-border)] mx-1" />
                <button
                  onClick={handleExport}
                  className="p-1.5 rounded-lg hover:bg-[var(--nc-surface-2)] transition-all text-[var(--nc-text-ghost)] hover:text-[var(--nc-text-secondary)]"
                  title="設定をエクスポート"
                  aria-label="Export settings"
                >
                  <Download size={14} />
                </button>
                <button
                  onClick={() => importInputRef.current?.click()}
                  className="p-1.5 rounded-lg hover:bg-[var(--nc-surface-2)] transition-all text-[var(--nc-text-ghost)] hover:text-[var(--nc-text-secondary)]"
                  title="設定をインポート"
                  aria-label="Import settings"
                >
                  <Upload size={14} />
                </button>
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleImportFile}
                  className="hidden"
                />
              </div>
            </div>

            {/* History Tab */}
            {activeTab === 'history' && history.length > 0 && (
              <div className="grid grid-cols-1 gap-2">
                {history.slice(0, 5).map((h) => (
                  <div
                    key={h.session_id}
                    onClick={() => restoreSession(h.session_id)}
                    className="flex items-center justify-between p-3.5 bg-[var(--nc-surface)] border border-[var(--nc-border)] rounded-xl hover:border-[rgba(99,102,241,0.2)] hover:bg-[var(--nc-surface-2)] transition-all cursor-pointer group"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-[11px] uppercase" style={{ background: 'var(--nc-primary-soft)', color: 'var(--nc-primary)' }}>
                        {h.key ? h.key.split(' ')[0] : 'N/A'}
                      </div>
                      <div>
                        <div className="font-semibold text-[var(--nc-text)] text-sm truncate max-w-[200px]">{h.filename}</div>
                        <div className="text-[10px] text-[var(--nc-text-ghost)] font-medium">{h.created_at || h.session_id}</div>
                      </div>
                    </div>
                    <ChevronRight size={16} className="text-[var(--nc-text-ghost)] group-hover:text-[var(--nc-primary)] group-hover:translate-x-0.5 transition-all" />
                  </div>
                ))}
              </div>
            )}

            {/* Favorites Tab */}
            {activeTab === 'favorites' && (
              <div className="grid grid-cols-1 gap-2">
                {/* Folder groups */}
                {folders.map(folderName => {
                  const items = getFavoritesByFolder ? getFavoritesByFolder(folderName) : [];
                  const isExpanded = expandedFolders[folderName] !== false; // default expanded
                  return (
                    <div key={folderName}>
                      <div
                        className="flex items-center justify-between p-2.5 rounded-xl hover:bg-[var(--nc-surface-2)] transition-all cursor-pointer group"
                        onClick={() => toggleFolderExpand(folderName)}
                      >
                        <div className="flex items-center gap-2">
                          {isExpanded ? <ChevronDown size={14} className="text-[var(--nc-text-muted)]" /> : <ChevronRight size={14} className="text-[var(--nc-text-muted)]" />}
                          <Folder size={14} className="text-[var(--nc-primary)]" />
                          <span className="text-xs font-bold text-[var(--nc-text-secondary)]">{folderName}</span>
                          <span className="text-[10px] text-[var(--nc-text-ghost)]">({items.length})</span>
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); deleteFolder(folderName); }}
                          className="p-1 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-[rgba(239,68,68,0.1)] transition-all text-[var(--nc-text-ghost)] hover:text-red-400"
                          title="フォルダを削除"
                          aria-label={`Delete folder ${folderName}`}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                      {isExpanded && items.length > 0 && (
                        <div className="ml-6 grid grid-cols-1 gap-1.5 mt-1">
                          <button
                            onClick={(e) => { e.stopPropagation(); startSetlist(folderName, items); }}
                            className="w-full text-left p-2.5 rounded-xl bg-[var(--nc-primary-soft)] text-[var(--nc-primary)] hover:bg-[var(--nc-primary)] hover:text-white transition-all font-bold text-xs flex items-center gap-2 mb-1"
                          >
                            <Play size={14} fill="currentColor" />
                            このセットリストを再生
                          </button>
                          {items.map(renderFavItem)}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* Uncategorized favorites */}
                {uncategorized.length > 0 && (
                  <>
                    {folders.length > 0 && (
                      <div className="flex items-center gap-2 p-2.5">
                        <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--nc-text-ghost)]">未分類</span>
                      </div>
                    )}
                    {uncategorized.map(renderFavItem)}
                  </>
                )}

                {/* Empty state */}
                {!hasFavorites && (
                  <div className="py-8 text-center">
                    <Star size={24} className="mx-auto mb-3 text-[var(--nc-text-ghost)]" />
                    <p className="text-sm text-[var(--nc-text-muted)]">お気に入りはまだありません</p>
                    <p className="text-xs text-[var(--nc-text-ghost)] mt-1">解析結果画面の ★ ボタンで追加できます</p>
                  </div>
                )}

                {/* Create folder button */}
                {!showNewFolder ? (
                  <button
                    onClick={() => setShowNewFolder(true)}
                    className="flex items-center gap-2 p-2.5 rounded-xl text-xs font-bold text-[var(--nc-text-muted)] hover:bg-[var(--nc-surface-2)] hover:text-[var(--nc-primary)] transition-all"
                  >
                    <FolderPlus size={14} /> フォルダ作成
                  </button>
                ) : (
                  <div className="flex items-center gap-2 p-2">
                    <input
                      type="text"
                      value={newFolderName}
                      onChange={(e) => setNewFolderName(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleCreateFolder(); if (e.key === 'Escape') { setShowNewFolder(false); setNewFolderName(''); } }}
                      placeholder="フォルダ名..."
                      autoFocus
                      className="flex-1 px-3 py-2 rounded-lg text-xs bg-[var(--nc-surface)] border border-[var(--nc-border)] text-[var(--nc-text)] placeholder-[var(--nc-text-muted)] focus:outline-none focus:border-[var(--nc-primary)] transition-all"
                    />
                    <button
                      onClick={handleCreateFolder}
                      disabled={!newFolderName.trim()}
                      className="px-3 py-2 rounded-lg text-xs font-bold transition-all"
                      style={{
                        background: newFolderName.trim() ? 'var(--nc-primary-soft)' : 'var(--nc-surface-2)',
                        color: newFolderName.trim() ? 'var(--nc-primary)' : 'var(--nc-text-muted)',
                      }}
                    >
                      作成
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
