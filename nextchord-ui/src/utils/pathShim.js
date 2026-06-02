/**
 * Minimal path shim for browser use.
 * kuromoji's DictionaryLoader only needs path.join() to construct dictionary URLs.
 */

export function join(...parts) {
  return parts
    .map((p, i) => {
      if (i > 0) p = p.replace(/^[/\\]+/, '');
      if (i < parts.length - 1) p = p.replace(/[/\\]+$/, '');
      return p;
    })
    .filter(p => p.length > 0)
    .join('/');
}

export default { join };
