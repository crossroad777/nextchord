/**
 * 文字の表示幅を計算する関数（半角=1, 全角=2と近似）
 */
export function getVisualWidth(str) {
    let width = 0;
    for (let i = 0; i < str.length; i++) {
        const code = str.charCodeAt(i);
        // 簡単な全角判定ヒューリスティック
        if (code >= 0x1100 &&
            (code <= 0x115f ||
             code === 0x2329 || code === 0x232a ||
             (code >= 0x2e80 && code <= 0xa4cf && code !== 0x303f) ||
             (code >= 0xac00 && code <= 0xd7a3) ||
             (code >= 0xf900 && code <= 0xfaff) ||
             (code >= 0xfe10 && code <= 0xfe19) ||
             (code >= 0xfe30 && code <= 0xfe6f) ||
             (code >= 0xff00 && code <= 0xff60) ||
             (code >= 0xffe0 && code <= 0xffe6))) {
            width += 2;
        } else {
            width += 1;
        }
    }
    return width;
}

/**
 * ChordPro形式（[C]歌詞）を2行スタイル（上がコード、下が歌詞）のプレーンテキストに変換する
 */
export function chordproToPlainText(chordproText) {
    if (!chordproText) return '';
    const lines = chordproText.split('\n');
    let result = '';

    for (const line of lines) {
        if (line.trim() === '') {
            result += '\n';
            continue;
        }
        if (line.trim().startsWith('{')) {
            // セクションタグ等はそのまま維持
            result += line + '\n';
            continue;
        }

        const regex = /\[([^\]]+)\]/g;
        const matches = [...line.matchAll(regex)];
        
        // コードが全く含まれていない行はそのまま出力
        if (matches.length === 0) {
            result += line + '\n';
            continue;
        }
        
        let chordLine = '';
        let lyricLine = '';
        let lastIdx = 0;
        let visualPos = 0;
        
        for (const match of matches) {
            const chord = match[1];
            const lyricsBefore = line.substring(lastIdx, match.index);
            
            lyricLine += lyricsBefore;
            visualPos += getVisualWidth(lyricsBefore);
            
            // chordLine の長さを visualPos に合わせるためにスペースで埋める
            while (chordLine.length < visualPos) {
                chordLine += ' ';
            }
            chordLine += chord + ' '; // コード同士がくっつかないように最低1スペース確保
            visualPos += chord.length + 1; // 実際に確保した幅を進める
            
            lastIdx = match.index + match[0].length;
        }
        
        lyricLine += line.substring(lastIdx);
        
        result += chordLine.trimEnd() + '\n' + lyricLine + '\n';
    }
    return result.trimEnd();
}

/**
 * 2行スタイルのプレーンテキストを元のChordPro形式に逆変換する
 */
export function plainTextToChordpro(plainText) {
    if (!plainText) return '';
    const lines = plainText.split('\n');
    let result = '';
    
    // コード行かどうかの判定関数
    const isChordLine = (str) => {
        if (str.trim() === '') return false;
        // 許可する文字: 英数字、#, b, +, -, /, (, ), 空白
        if (!/^[A-Za-z0-9#\+\-\/\(\)\s]+$/.test(str)) return false;
        // 大文字の A-G が少なくとも1つ含まれているか
        if (!/[A-G]/.test(str)) return false;
        
        // スペース区切りの各ブロックがA-Gで始まっているかチェック（緩めに）
        const words = str.trim().split(/\s+/);
        for (const w of words) {
            // "sus4" のようにアルファベット小文字だけで構成されているものはNG（コードの構成要素とみなすならA-G始まりのはず）
            if (!/^[A-G]/.test(w) && !/^\(/.test(w)) {
                return false;
            }
        }
        return true;
    };

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];
        
        if (line.trim().startsWith('{')) {
            result += line + '\n';
            continue;
        }
        
        if (isChordLine(line)) {
            // 次の行が歌詞かどうかチェック（次の行が存在し、かつコード行でもセクションでもない）
            if (i + 1 < lines.length && !isChordLine(lines[i+1]) && !lines[i+1].trim().startsWith('{') && lines[i+1].trim() !== '') {
                const chordLine = line;
                const lyricLine = lines[i+1];
                i++; // 歌詞行を消費
                
                // コード行からコードとその位置を抽出
                const chordRegex = /[A-Ga-g][^\s]*/g;
                let match;
                const chords = [];
                while ((match = chordRegex.exec(chordLine)) !== null) {
                    chords.push({ chord: match[0], pos: match.index });
                }
                
                // 歌詞とコードをマージ
                let mergedLine = '';
                let currentLyricVisualPos = 0;
                let currentLyricCharIdx = 0;
                let chordIdx = 0;
                
                // 歌詞の文字を1つずつ進めながら、位置が合致するコードを挿入
                while (currentLyricCharIdx < lyricLine.length || chordIdx < chords.length) {
                    // 現在の視覚位置（またはそれ以前）にあるコードを挿入
                    while (chordIdx < chords.length && chords[chordIdx].pos <= currentLyricVisualPos) {
                        mergedLine += `[${chords[chordIdx].chord}]`;
                        chordIdx++;
                    }
                    
                    if (currentLyricCharIdx < lyricLine.length) {
                        const char = lyricLine[currentLyricCharIdx];
                        mergedLine += char;
                        currentLyricVisualPos += getVisualWidth(char);
                        currentLyricCharIdx++;
                    } else {
                        // 歌詞が終わってもコードが残っている場合（行末にコードがある場合）
                        while (chordIdx < chords.length) {
                            mergedLine += `[${chords[chordIdx].chord}]`;
                            chordIdx++;
                        }
                        break;
                    }
                }
                result += mergedLine + '\n';
            } else {
                // 歌詞がないコード行のみの場合（[C] [G] のように変換）
                const chordRegex = /[A-Ga-g][^\s]*/g;
                let merged = line.replace(chordRegex, match => `[${match}]`);
                merged = merged.replace(/\s+/g, ' ').trim();
                result += merged + '\n';
            }
        } else {
            // 単なる歌詞行（または空行）
            result += line + '\n';
        }
    }
    return result.trimEnd();
}
