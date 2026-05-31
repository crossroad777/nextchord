/**
 * kuromojiTokenizer.js
 *
 * Singleton wrapper around kuromoji.js for Japanese morphological analysis.
 * Used to re-segment Whisper's character-level tokens into proper word units
 * while preserving original timestamps.
 *
 * Whisper problem:  ["め", "ぐ", "り", "逢", "いた", "い"]
 * After kuromoji:   ["めぐり逢い", "たい"]  (proper morphological boundaries)
 */
import kuromoji from 'kuromoji';

// ── Singleton tokenizer ──────────────────────────────────────────────────
let _tokenizer = null;
let _initPromise = null;
let _initFailed = false;

/**
 * Initialize the kuromoji tokenizer (called once).
 * Dictionary files are served from /dict/ in the public directory.
 */
export function initTokenizer() {
  if (_tokenizer) return Promise.resolve(_tokenizer);
  if (_initPromise) return _initPromise;

  _initPromise = new Promise((resolve, reject) => {
    // Dictionary path: served from public/dict/ via Vite
    const dictPath = `${window.location.origin}/dict/`;

    kuromoji.builder({ dicPath: dictPath }).build((err, tokenizer) => {
      if (err) {
        console.error('[kuromoji] Failed to initialize tokenizer:', err);
        _initFailed = true;
        _initPromise = null;
        reject(err);
        return;
      }
      console.log('[kuromoji] Tokenizer initialized successfully');
      _tokenizer = tokenizer;
      resolve(tokenizer);
    });
  });

  return _initPromise;
}

/**
 * Check if the tokenizer is ready.
 */
export function isTokenizerReady() {
  return _tokenizer !== null;
}

/**
 * Get the tokenizer instance (null if not initialized yet).
 */
export function getTokenizer() {
  return _tokenizer;
}

// ── Helper: classify if a character is "word-like" ──────────────────────
function isWordChar(ch) {
  if (!ch) return false;
  const cp = ch.codePointAt(0);
  // Hiragana, Katakana, CJK Unified Ideographs, Halfwidth/Fullwidth
  return (cp >= 0x3040 && cp <= 0x309F) || // Hiragana
         (cp >= 0x30A0 && cp <= 0x30FF) || // Katakana
         (cp >= 0x4E00 && cp <= 0x9FFF) || // CJK
         (cp >= 0xFF66 && cp <= 0xFF9F) || // Halfwidth Katakana
         (cp >= 0x3400 && cp <= 0x4DBF) || // CJK Extension A
         (cp >= 0x0041 && cp <= 0x005A) || // A-Z
         (cp >= 0x0061 && cp <= 0x007A) || // a-z
         (cp >= 0xFF21 && cp <= 0xFF3A) || // Ａ-Ｚ
         (cp >= 0xFF41 && cp <= 0xFF5A);   // ａ-ｚ
}

/**
 * Re-segment Whisper word-level tokens using kuromoji morphological analysis.
 *
 * @param {Array<{word?: string, w?: string, start?: number, s?: number, end?: number, e?: number}>} whisperWords
 *   Whisper's word-level tokens with timestamps.
 * @returns {Array<{word: string, start: number, end: number}>}
 *   Re-segmented words with proper Japanese word boundaries and preserved timestamps.
 */
export function resegmentWords(whisperWords) {
  if (!whisperWords || whisperWords.length === 0) return [];
  if (!_tokenizer) {
    // Fallback: return original words as-is
    return whisperWords.map(w => ({
      word: w.word ?? w.w ?? '',
      start: w.start ?? w.s ?? 0,
      end: w.end ?? w.e ?? 0,
    }));
  }

  // 1. Build the full text and a char→whisperToken mapping
  const fullText = whisperWords.map(w => w.word ?? w.w ?? '').join('');
  if (fullText.length === 0) return [];

  // charTimestamps[i] = { start, end, whisperIdx } for the i-th character
  const charTimestamps = [];
  for (let wi = 0; wi < whisperWords.length; wi++) {
    const w = whisperWords[wi];
    const text = w.word ?? w.w ?? '';
    const wStart = w.start ?? w.s ?? 0;
    const wEnd = w.end ?? w.e ?? wStart;
    // Distribute timestamps evenly within each Whisper token
    const charCount = text.length;
    for (let ci = 0; ci < charCount; ci++) {
      const charStart = charCount > 1
        ? wStart + (wEnd - wStart) * (ci / charCount)
        : wStart;
      const charEnd = charCount > 1
        ? wStart + (wEnd - wStart) * ((ci + 1) / charCount)
        : wEnd;
      charTimestamps.push({ start: charStart, end: charEnd, whisperIdx: wi });
    }
  }

  // 2. Run kuromoji tokenization
  const kuroTokens = _tokenizer.tokenize(fullText);

  // 3. Map kuromoji tokens back to timestamps
  const result = [];
  let charPos = 0;

  for (const kt of kuroTokens) {
    const surface = kt.surface_form;
    const tokenLen = surface.length;

    if (tokenLen === 0) continue;

    // Skip pure punctuation / whitespace tokens
    const hasMeaningfulChar = [...surface].some(ch => isWordChar(ch));

    const startCharIdx = charPos;
    const endCharIdx = charPos + tokenLen - 1;

    if (startCharIdx < charTimestamps.length && endCharIdx < charTimestamps.length) {
      const tokenStart = charTimestamps[startCharIdx].start;
      const tokenEnd = charTimestamps[endCharIdx].end;

      if (hasMeaningfulChar) {
        result.push({
          word: surface,
          start: tokenStart,
          end: tokenEnd,
        });
      } else {
        // Punctuation: attach to previous word if possible
        if (result.length > 0) {
          result[result.length - 1].word += surface;
          result[result.length - 1].end = tokenEnd;
        } else {
          result.push({ word: surface, start: tokenStart, end: tokenEnd });
        }
      }
    }

    charPos += tokenLen;
  }

  return result;
}

/**
 * Compute word-index break points for line splitting.
 * Returns an array of word indices where it's "safe" to break a line.
 *
 * Strategy: break BEFORE particles (助詞), conjunctions (接続詞),
 * and at content-word boundaries (noun/verb starts after another word).
 *
 * @param {Array<{word: string, start: number, end: number}>} resegmentedWords
 * @returns {number[]} Array of word indices suitable for line breaks.
 */
export function computeBreaks(resegmentedWords) {
  if (!resegmentedWords || resegmentedWords.length < 2) return [];
  if (!_tokenizer) return [];

  const fullText = resegmentedWords.map(w => w.word).join('');
  const kuroTokens = _tokenizer.tokenize(fullText);

  // Map kuromoji tokens to resegmented word indices
  // Each resegmented word may span one or more kuromoji tokens (should be 1:1 ideally)
  const breaks = new Set();

  // Walk through kuromoji tokens and find good break points
  let charPos = 0;
  let wordIdx = 0;
  let wordCharPos = 0;

  // Build a character→wordIdx map for the resegmented words
  const charToWordIdx = [];
  for (let wi = 0; wi < resegmentedWords.length; wi++) {
    const wLen = resegmentedWords[wi].word.length;
    for (let ci = 0; ci < wLen; ci++) {
      charToWordIdx.push(wi);
    }
  }

  for (let ti = 0; ti < kuroTokens.length; ti++) {
    const kt = kuroTokens[ti];
    const surface = kt.surface_form;
    const startChar = charPos;
    charPos += surface.length;

    if (startChar >= charToWordIdx.length) continue;
    const wi = charToWordIdx[startChar];

    // Good break points: before content words that start a new resegmented word
    if (wi > 0 && startChar === sumLengths(resegmentedWords, wi)) {
      const pos = kt.pos; // part-of-speech
      // Break before: nouns (名詞), verbs (動詞), adjectives (形容詞),
      // adverbs (副詞), conjunctions (接続詞), interjections (感動詞)
      if (pos === '名詞' || pos === '動詞' || pos === '形容詞' ||
          pos === '副詞' || pos === '接続詞' || pos === '感動詞' ||
          pos === '連体詞' || pos === '接頭詞') {
        breaks.add(wi);
      }
    }
  }

  return [...breaks].sort((a, b) => a - b);
}

function sumLengths(words, upToIdx) {
  let sum = 0;
  for (let i = 0; i < upToIdx; i++) {
    sum += words[i].word.length;
  }
  return sum;
}
