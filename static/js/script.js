/**
 * ═══════════════════════════════════════════════════════════════════════
 * SEO Content Analyzer — Client-Side Analysis Engine (CKEditor 5 Edition)
 * ═══════════════════════════════════════════════════════════════════════
 *
 * Key change from v1: the content editor is now CKEditor 5 (rich-text),
 * so we parse HTML output instead of markdown.  Headings come from
 * <h1>–<h6> tags, paragraphs from <p> tags, and plain text is extracted
 * by stripping all HTML before running word/sentence analysis.
 *
 * Architecture:
 *   1. CKEditor initialisation
 *   2. Utility helpers  (HTML→text, sentence splitting, etc.)
 *   3. Analysis modules  (SEO checks, readability checks)
 *   4. UI renderers      (score rings, check lists, suggestions)
 *   5. Bootstrap          (event wiring, dark-mode, export)
 */

// ─────────────────────────────────────────────────────────────────────
// 0. DOM REFERENCES
// ─────────────────────────────────────────────────────────────────────
const dom = {
  keyword:        document.getElementById('focus-keyword'),
  seoTitle:       document.getElementById('seo-title'),
  seoSlug:        document.getElementById('seo-slug'),
  metaDesc:       document.getElementById('meta-desc'),
  contentTextarea:document.getElementById('content-editor'),   // CKEditor replaces this
  wordCount:      document.getElementById('word-count'),
  charCount:      document.getElementById('char-count'),
  paragraphCount: document.getElementById('paragraph-count'),
  sentenceCount:  document.getElementById('sentence-count'),
  seoTitleCount:  document.getElementById('seo-title-count'),
  metaDescCount:  document.getElementById('meta-desc-count'),
  // Desktop snippet elements
  snippetDTitle:  document.getElementById('snippet-d-title'),
  snippetDSlug:   document.getElementById('snippet-d-slug'),
  snippetDDesc:   document.getElementById('snippet-d-desc'),
  // Mobile snippet elements
  snippetMTitle:  document.getElementById('snippet-m-title'),
  snippetMSlug:   document.getElementById('snippet-m-slug'),
  snippetMDesc:   document.getElementById('snippet-m-desc'),
  // Snippet containers & tabs
  snippetDesktop: document.getElementById('snippet-desktop'),
  snippetMobile:  document.getElementById('snippet-mobile'),
  tabDesktop:     document.getElementById('tab-desktop'),
  tabMobile:      document.getElementById('tab-mobile'),
  seoScoreRing:   document.getElementById('seo-score-ring'),
  seoScoreLabel:  document.getElementById('seo-score-label'),
  readScoreRing:  document.getElementById('read-score-ring'),
  readScoreLabel: document.getElementById('read-score-label'),
  seoChecks:      document.getElementById('seo-checks'),
  readChecks:     document.getElementById('readability-checks'),
  headingStruct:  document.getElementById('heading-structure'),
  suggestions:    document.getElementById('suggestions-list'),
  btnDarkMode:    document.getElementById('btn-darkmode'),
  btnExport:      document.getElementById('btn-export'),
};

/** Global reference to the CKEditor instance — set after init. */
let editorInstance = null;


// ─────────────────────────────────────────────────────────────────────
// 1. CKEditor 5 INITIALISATION
// ─────────────────────────────────────────────────────────────────────

/**
 * Boot CKEditor 5 ClassicEditor on the <textarea>.
 * The toolbar includes headings, basic formatting, lists, links,
 * block-quotes, and undo/redo — everything needed for SEO content.
 */
function initEditor() {
  ClassicEditor
    .create(dom.contentTextarea, {
      toolbar: [
        'heading', '|',
        'bold', 'italic', 'underline', '|',
        'link', 'bulletedList', 'numberedList', 'blockQuote', '|',
        'undo', 'redo',
      ],
      heading: {
        options: [
          { model: 'paragraph',  title: 'Paragraph',  class: 'ck-heading_paragraph' },
          { model: 'heading1',   view: 'h1', title: 'Heading 1', class: 'ck-heading_heading1' },
          { model: 'heading2',   view: 'h2', title: 'Heading 2', class: 'ck-heading_heading2' },
          { model: 'heading3',   view: 'h3', title: 'Heading 3', class: 'ck-heading_heading3' },
          { model: 'heading4',   view: 'h4', title: 'Heading 4', class: 'ck-heading_heading4' },
          { model: 'heading5',   view: 'h5', title: 'Heading 5', class: 'ck-heading_heading5' },
          { model: 'heading6',   view: 'h6', title: 'Heading 6', class: 'ck-heading_heading6' },
        ],
      },
      placeholder: 'Start writing your content here…',
    })
    .then(editor => {
      editorInstance = editor;

      // Re-run analysis every time the editor content changes
      const analyse = debounce(runAnalysis, 200);
      editor.model.document.on('change:data', analyse);

      // Run once immediately
      runAnalysis();
    })
    .catch(err => console.error('CKEditor init error:', err));
}


// ─────────────────────────────────────────────────────────────────────
// 2. UTILITY HELPERS
// ─────────────────────────────────────────────────────────────────────

/** Debounce wrapper — limits callback to once every `ms` milliseconds. */
function debounce(fn, ms = 200) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/**
 * Strip HTML tags and return plain text.
 * Uses a temporary DOM element for accurate parsing.
 */
function htmlToPlainText(html) {
  const el = document.createElement('div');
  el.innerHTML = html;
  return el.textContent || el.innerText || '';
}

/**
 * Split text into an array of sentences.
 * Splits on period / question-mark / exclamation followed by whitespace.
 */
function getSentences(text) {
  if (!text.trim()) return [];
  return text
    .replace(/\n+/g, ' ')
    .split(/(?<=[.?!])\s+/)
    .filter(s => s.trim().length > 0);
}

/**
 * Get paragraphs from CKEditor HTML.
 * Extracts text content of each <p> tag.
 */
function getParagraphsFromHtml(html) {
  const el = document.createElement('div');
  el.innerHTML = html;
  const pTags = el.querySelectorAll('p');
  const result = [];
  pTags.forEach(p => {
    const txt = (p.textContent || '').trim();
    if (txt.length > 0) result.push(txt);
  });
  // If there are no <p> tags fall back to splitting plain text on blank lines
  if (result.length === 0) {
    const plain = htmlToPlainText(html);
    return plain.split(/\n\s*\n/).filter(p => p.trim().length > 0);
  }
  return result;
}

/** Count words in a string. */
function wordCount(text) {
  const words = text.trim().split(/\s+/).filter(w => w.length > 0);
  return words.length;
}

/**
 * Extract headings (<h1>–<h6>) from CKEditor HTML.
 * Returns [{ level: 1–6, text: '…' }, …].
 */
function getHeadingsFromHtml(html) {
  const el = document.createElement('div');
  el.innerHTML = html;
  const headings = [];
  el.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(node => {
    const level = parseInt(node.tagName.charAt(1), 10);
    const text = (node.textContent || '').trim();
    if (text) headings.push({ level, text });
  });
  return headings;
}

/** Escape regex special characters. */
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Count occurrences of a keyword/phrase (case-insensitive, whole-word).
 */
function countKeyword(text, keyword) {
  if (!keyword.trim()) return 0;
  const regex = new RegExp('\\b' + escapeRegex(keyword.trim()) + '\\b', 'gi');
  return (text.match(regex) || []).length;
}

// ─── Stop-word list (common English) ────────────────────────────────
const STOP_WORDS = new Set([
  'a','about','above','after','again','against','all','am','an','and','any',
  'are','as','at','be','because','been','before','being','below','between',
  'both','but','by','cannot','could','did','do','does','doing','down',
  'during','each','few','for','from','further','get','got','had','has',
  'have','having','he','her','here','hers','herself','him','himself','his',
  'how','i','if','in','into','is','it','its','itself','just','me','more',
  'most','my','myself','no','nor','not','of','off','on','once','only','or',
  'other','ought','our','ours','ourselves','out','over','own','same','she',
  'should','so','some','such','than','that','the','their','theirs','them',
  'themselves','then','there','these','they','this','those','through','to',
  'too','under','until','up','very','was','we','were','what','when','where',
  'which','while','who','whom','why','will','with','would','you','your',
  'yours','yourself','yourselves',
]);

/** Remove stop words, return remaining words lowercased. */
function removeStopWords(text) {
  return text.toLowerCase().split(/\s+/).filter(w => w.length > 1 && !STOP_WORDS.has(w));
}

// ─── Transition words ───────────────────────────────────────────────
const TRANSITION_WORDS = [
  'additionally','also','moreover','furthermore','in addition','besides',
  'however','nevertheless','nonetheless','on the other hand','in contrast',
  'conversely','although','though','even though','whereas','while',
  'therefore','consequently','as a result','thus','hence','accordingly',
  'for example','for instance','such as','in particular','specifically',
  'namely','first','second','third','finally','meanwhile','subsequently',
  'next','then','afterward','previously','before','after','during',
  'in conclusion','to summarize','in summary','overall','in short',
  'similarly','likewise','in the same way','compared to','just as',
  'because','since','due to','owing to','in order to','so that',
  'indeed','certainly','undoubtedly','of course','in fact','above all',
];

/** Count sentences starting with a transition word/phrase. */
function countTransitionSentences(sentences) {
  let count = 0;
  for (const s of sentences) {
    const lower = s.trim().toLowerCase();
    if (TRANSITION_WORDS.some(tw => lower.startsWith(tw))) count++;
  }
  return { count, total: sentences.length };
}

// ─── Passive voice heuristic ────────────────────────────────────────
const PASSIVE_RE =
  /\b(?:am|is|are|was|were|been|being|be)\s+(\w+ed|built|chosen|come|done|drawn|driven|eaten|fallen|felt|found|given|gone|grown|heard|held|hidden|hit|kept|known|laid|led|left|lent|lost|made|meant|met|paid|put|read|ridden|run|said|seen|sent|set|shown|shut|spoken|spent|stood|struck|taken|taught|thought|thrown|told|understood|won|worn|written)\b/gi;

function countPassiveSentences(sentences) {
  let count = 0;
  for (const s of sentences) {
    if (PASSIVE_RE.test(s)) count++;
    PASSIVE_RE.lastIndex = 0;
  }
  return { count, total: sentences.length };
}

/** Estimate syllable count for an English word. */
function countSyllables(word) {
  word = word.toLowerCase().replace(/[^a-z]/g, '');
  if (word.length <= 2) return 1;
  word = word.replace(/e$/, '');
  const matches = word.match(/[aeiouy]+/g);
  return matches ? Math.max(1, matches.length) : 1;
}

/**
 * Content Readability score.
 * 206.835 − 1.015×(words/sentences) − 84.6×(syllables/words)
 */
function fleschReadingEase(text) {
  const sentences = getSentences(text);
  const words = text.trim().split(/\s+/).filter(w => w.length > 0);
  if (words.length === 0 || sentences.length === 0) return 0;
  const totalSyllables = words.reduce((sum, w) => sum + countSyllables(w), 0);
  const score = 206.835 - 1.015 * (words.length / sentences.length) - 84.6 * (totalSyllables / words.length);
  return Math.max(0, Math.min(100, Math.round(score)));
}

/** Keyword variation detection (singular/plural, word-order). */
function getKeywordVariations(keyword) {
  if (!keyword.trim()) return [];
  const kw = keyword.trim().toLowerCase();
  const words = kw.split(/\s+/);
  const variations = new Set();

  for (const w of words) {
    if (w.endsWith('s')) variations.add(w.slice(0, -1));
    else variations.add(w + 's');
    if (w.endsWith('ies')) variations.add(w.slice(0, -3) + 'y');
    if (w.endsWith('y') && !w.endsWith('ey')) variations.add(w.slice(0, -1) + 'ies');
  }
  if (words.length > 1) {
    variations.add(words.slice().reverse().join(' '));
  }
  variations.delete(kw);
  return [...variations];
}

/**
 * Keyword distribution — divide content into 4 quarters,
 * check how many quarters contain the keyword.
 */
function keywordDistribution(text, keyword) {
  if (!keyword.trim() || !text.trim()) return { score: 0, detail: 'No content yet.' };
  const len = text.length;
  const quarter = Math.ceil(len / 4);
  let found = 0;
  for (let i = 0; i < 4; i++) {
    const chunk = text.slice(i * quarter, (i + 1) * quarter);
    if (countKeyword(chunk, keyword) > 0) found++;
  }
  if (found >= 4) return { score: 1,    detail: 'Keyword is well distributed across all sections.' };
  if (found >= 3) return { score: 0.75, detail: `Keyword found in ${found}/4 sections. Good distribution.` };
  if (found >= 2) return { score: 0.5,  detail: `Keyword found in ${found}/4 sections. Try spreading it more evenly.` };
  return { score: 0.25, detail: `Keyword found in only ${found}/4 sections. Distribute it more evenly.` };
}


// ─────────────────────────────────────────────────────────────────────
// 3. ANALYSIS MODULES
// ─────────────────────────────────────────────────────────────────────

/**
 * Run all SEO checks.
 * `contentHtml` is CKEditor's raw HTML output.
 * `contentPlain` is the stripped plain-text version.
 */
function runSeoChecks(contentPlain, contentHtml, keyword, title, metaDesc, slug) {
  const checks = [];
  const words = wordCount(contentPlain);
  const kw = keyword.trim().toLowerCase();

  // ── 1. Content length ──────────────────────────────────────────────
  if (words >= 900) {
    checks.push({ id: 'length', label: 'Content length', status: 'good',
      detail: `${words} words — great, your content has a good length.` });
  } else if (words >= 300) {
    checks.push({ id: 'length', label: 'Content length', status: 'ok',
      detail: `${words} words — aim for at least 900 words for in-depth content.` });
  } else {
    checks.push({ id: 'length', label: 'Content length', status: 'poor',
      detail: `${words} words — too short. Write at least 300 words.` });
  }

  // ── 2. Keyword density (ideal: 0.5 – 2.5%) ────────────────────────
  if (kw) {
    const freq = countKeyword(contentPlain, kw);
    const density = words > 0 ? (freq / words) * 100 : 0;
    const d = density.toFixed(2);

    if (density >= 0.5 && density <= 2.5) {
      checks.push({ id: 'density', label: 'Keyword density', status: 'good',
        detail: `${d}% — keyword appears ${freq} time(s). Ideal range.` });
    } else if (density > 2.5) {
      checks.push({ id: 'density', label: 'Keyword density', status: 'poor',
        detail: `${d}% — keyword stuffing detected (${freq} times). Reduce usage.` });
    } else if (density > 0) {
      checks.push({ id: 'density', label: 'Keyword density', status: 'ok',
        detail: `${d}% — keyword appears ${freq} time(s). Try to reach 0.5%.` });
    } else {
      checks.push({ id: 'density', label: 'Keyword density', status: 'poor',
        detail: 'Keyword not found in content.' });
    }
  } else {
    checks.push({ id: 'density', label: 'Keyword density', status: 'poor',
      detail: 'No focus keyword set.' });
  }

  // ── 3. Keyword in first paragraph ──────────────────────────────────
  if (kw) {
    const paragraphs = getParagraphsFromHtml(contentHtml);
    const firstPara = paragraphs.length > 0 ? paragraphs[0].toLowerCase() : '';
    if (countKeyword(firstPara, kw) > 0) {
      checks.push({ id: 'first-para', label: 'Keyword in introduction', status: 'good',
        detail: 'Keyword appears in the first paragraph.' });
    } else {
      checks.push({ id: 'first-para', label: 'Keyword in introduction', status: 'poor',
        detail: 'Keyword missing from the first paragraph. Add it early.' });
    }
  }

  // ── 4. Keyword in headings (parsed from HTML <h1>–<h6>) ───────────
  if (kw) {
    const headings = getHeadingsFromHtml(contentHtml);
    const inHeading = headings.some(h => countKeyword(h.text, kw) > 0);
    if (headings.length === 0) {
      checks.push({ id: 'kw-heading', label: 'Keyword in headings', status: 'poor',
        detail: 'No headings found. Add headings with your keyword.' });
    } else if (inHeading) {
      checks.push({ id: 'kw-heading', label: 'Keyword in headings', status: 'good',
        detail: 'Keyword found in at least one heading.' });
    } else {
      checks.push({ id: 'kw-heading', label: 'Keyword in headings', status: 'ok',
        detail: 'Keyword not found in any heading. Include it in a subheading.' });
    }
  }

  // ── 5. Keyword distribution ────────────────────────────────────────
  if (kw && words >= 100) {
    const dist = keywordDistribution(contentPlain, kw);
    const status = dist.score >= 0.75 ? 'good' : dist.score >= 0.5 ? 'ok' : 'poor';
    checks.push({ id: 'kw-dist', label: 'Keyword distribution', status, detail: dist.detail });
  }

  // ── 6. SEO Title ───────────────────────────────────────────────────
  const titleLen = title.length;
  if (titleLen === 0) {
    checks.push({ id: 'title-len', label: 'SEO title', status: 'poor', detail: 'No SEO title set.' });
  } else if (titleLen < 30) {
    checks.push({ id: 'title-len', label: 'SEO title length', status: 'ok',
      detail: `${titleLen} chars — too short. Aim for 50–60.` });
  } else if (titleLen <= 60) {
    checks.push({ id: 'title-len', label: 'SEO title length', status: 'good',
      detail: `${titleLen} chars — good length.` });
  } else {
    checks.push({ id: 'title-len', label: 'SEO title length', status: 'poor',
      detail: `${titleLen} chars — too long, may be truncated.` });
  }

  if (kw && title) {
    if (title.toLowerCase().includes(kw)) {
      checks.push({ id: 'kw-title', label: 'Keyword in SEO title', status: 'good',
        detail: 'Focus keyword appears in the SEO title.' });
    } else {
      checks.push({ id: 'kw-title', label: 'Keyword in SEO title', status: 'poor',
        detail: 'Focus keyword missing from SEO title.' });
    }
  }

  // ── 7. Meta description ────────────────────────────────────────────
  const descLen = metaDesc.length;
  if (descLen === 0) {
    checks.push({ id: 'meta-len', label: 'Meta description', status: 'poor', detail: 'No meta description set.' });
  } else if (descLen < 120) {
    checks.push({ id: 'meta-len', label: 'Meta description length', status: 'ok',
      detail: `${descLen} chars — a bit short. Aim for 120–160.` });
  } else if (descLen <= 160) {
    checks.push({ id: 'meta-len', label: 'Meta description length', status: 'good',
      detail: `${descLen} chars — perfect length.` });
  } else {
    checks.push({ id: 'meta-len', label: 'Meta description length', status: 'poor',
      detail: `${descLen} chars — too long, will be truncated.` });
  }

  if (kw && metaDesc) {
    if (metaDesc.toLowerCase().includes(kw)) {
      checks.push({ id: 'kw-meta', label: 'Keyword in meta description', status: 'good',
        detail: 'Focus keyword appears in the meta description.' });
    } else {
      checks.push({ id: 'kw-meta', label: 'Keyword in meta description', status: 'ok',
        detail: 'Focus keyword missing from meta description.' });
    }
  }

  // ── 8. Keyword in slug ─────────────────────────────────────────────
  if (kw && slug) {
    const slugLower = slug.toLowerCase().replace(/-/g, ' ');
    if (slugLower.includes(kw)) {
      checks.push({ id: 'kw-slug', label: 'Keyword in URL slug', status: 'good',
        detail: 'Focus keyword appears in the slug.' });
    } else {
      checks.push({ id: 'kw-slug', label: 'Keyword in URL slug', status: 'ok',
        detail: 'Consider adding the focus keyword to the URL slug.' });
    }
  }

  // ── 9. Keyword variations ──────────────────────────────────────────
  if (kw) {
    const variations = getKeywordVariations(kw);
    const found = variations.filter(v => countKeyword(contentPlain, v) > 0);
    if (found.length > 0) {
      checks.push({ id: 'kw-var', label: 'Keyword variations', status: 'good',
        detail: `Found variations: "${found.join('", "')}". Good for natural language.` });
    } else if (variations.length > 0) {
      checks.push({ id: 'kw-var', label: 'Keyword variations', status: 'ok',
        detail: `No keyword variations found. Try using: "${variations.slice(0, 3).join('", "')}".` });
    }
  }

  return checks;
}

/** Run all readability checks on plain text. */
function runReadabilityChecks(contentPlain, contentHtml) {
  const checks = [];
  const sentences = getSentences(contentPlain);
  const paragraphs = getParagraphsFromHtml(contentHtml);
  const words = wordCount(contentPlain);

  // ── 1. Content Readability ─────────────────────────────────────────
  if (words >= 50) {
    const fre = fleschReadingEase(contentPlain);
    let status, label;
    if (fre >= 60) { status = 'good'; label = `Content Readability: ${fre} — easy to read.`; }
    else if (fre >= 30) { status = 'ok'; label = `Content Readability: ${fre} — fairly difficult. Simplify sentences.`; }
    else { status = 'poor'; label = `Content Readability: ${fre} — very difficult to read.`; }
    checks.push({ id: 'flesch', label: 'Content Readability', status, detail: label });
  } else {
    checks.push({ id: 'flesch', label: 'Content Readability', status: 'ok',
      detail: 'Need at least 50 words to calculate readability.' });
  }

  // ── 2. Average sentence length ─────────────────────────────────────
  if (sentences.length > 0) {
    const avg = Math.round(words / sentences.length);
    if (avg <= 20) {
      checks.push({ id: 'sent-len', label: 'Average sentence length', status: 'good',
        detail: `${avg} words per sentence — good.` });
    } else if (avg <= 25) {
      checks.push({ id: 'sent-len', label: 'Average sentence length', status: 'ok',
        detail: `${avg} words per sentence — try to keep it under 20.` });
    } else {
      checks.push({ id: 'sent-len', label: 'Average sentence length', status: 'poor',
        detail: `${avg} words per sentence — too long. Break up sentences.` });
    }
  }

  // ── 3. Long sentences (>25 words) ──────────────────────────────────
  if (sentences.length > 0) {
    const longOnes = sentences.filter(s => wordCount(s) > 25);
    const pct = Math.round((longOnes.length / sentences.length) * 100);
    if (pct <= 10) {
      checks.push({ id: 'long-sent', label: 'Long sentences', status: 'good',
        detail: `${pct}% of sentences are too long — excellent.` });
    } else if (pct <= 25) {
      checks.push({ id: 'long-sent', label: 'Long sentences', status: 'ok',
        detail: `${pct}% of sentences exceed 25 words. Try to reduce this.` });
    } else {
      checks.push({ id: 'long-sent', label: 'Long sentences', status: 'poor',
        detail: `${pct}% of sentences are too long. Shorten them for readability.` });
    }
  }

  // ── 4. Paragraph length ────────────────────────────────────────────
  if (paragraphs.length > 0) {
    const longParas = paragraphs.filter(p => wordCount(p) > 150);
    if (longParas.length === 0) {
      checks.push({ id: 'para-len', label: 'Paragraph length', status: 'good',
        detail: 'All paragraphs are a reasonable length.' });
    } else {
      checks.push({ id: 'para-len', label: 'Paragraph length', status: 'ok',
        detail: `${longParas.length} paragraph(s) exceed 150 words. Consider splitting them.` });
    }
  }

  // ── 5. Passive voice ───────────────────────────────────────────────
  if (sentences.length > 0) {
    const passive = countPassiveSentences(sentences);
    const pct = Math.round((passive.count / passive.total) * 100);
    if (pct <= 10) {
      checks.push({ id: 'passive', label: 'Passive voice', status: 'good',
        detail: `${pct}% of sentences use passive voice — great.` });
    } else if (pct <= 20) {
      checks.push({ id: 'passive', label: 'Passive voice', status: 'ok',
        detail: `${pct}% of sentences use passive voice. Try to use more active voice.` });
    } else {
      checks.push({ id: 'passive', label: 'Passive voice', status: 'poor',
        detail: `${pct}% of sentences use passive voice. Rewrite with active voice.` });
    }
  }

  // ── 6. Transition words ────────────────────────────────────────────
  if (sentences.length > 0) {
    const trans = countTransitionSentences(sentences);
    const pct = Math.round((trans.count / trans.total) * 100);
    if (pct >= 30) {
      checks.push({ id: 'transition', label: 'Transition words', status: 'good',
        detail: `${pct}% of sentences contain transition words — excellent flow.` });
    } else if (pct >= 15) {
      checks.push({ id: 'transition', label: 'Transition words', status: 'ok',
        detail: `${pct}% of sentences use transition words. Aim for 30%+.` });
    } else {
      checks.push({ id: 'transition', label: 'Transition words', status: 'poor',
        detail: `${pct}% — not enough transition words. Add words like "however", "therefore", "for example".` });
    }
  }

  return checks;
}


// ─────────────────────────────────────────────────────────────────────
// 4. SCORING
// ─────────────────────────────────────────────────────────────────────

/** Compute 0–100 score: good=1, ok=0.5, poor=0. */
function computeScore(checks) {
  if (checks.length === 0) return 0;
  const total = checks.reduce((sum, c) => {
    if (c.status === 'good') return sum + 1;
    if (c.status === 'ok')   return sum + 0.5;
    return sum;
  }, 0);
  return Math.round((total / checks.length) * 100);
}


// ─────────────────────────────────────────────────────────────────────
// 5. SUGGESTION ENGINE
// ─────────────────────────────────────────────────────────────────────

function generateSuggestions(seoChecks, readChecks, contentPlain, contentHtml, keyword) {
  const tips = [];

  for (const c of [...seoChecks, ...readChecks]) {
    if (c.status === 'poor') tips.push({ severity: 'poor', text: c.detail });
    else if (c.status === 'ok') tips.push({ severity: 'ok', text: c.detail });
  }

  const words = wordCount(contentPlain);
  if (words > 0 && words < 300) {
    tips.push({ severity: 'poor', text: 'Your content is thin. Aim for at least 300 words, ideally 900+.' });
  }

  const headings = getHeadingsFromHtml(contentHtml);
  if (words >= 300 && headings.length === 0) {
    tips.push({ severity: 'ok', text: 'Add headings to break up your content and improve scannability.' });
  }

  if (keyword.trim()) {
    const variations = getKeywordVariations(keyword.trim().toLowerCase());
    const found = variations.filter(v => countKeyword(contentPlain, v) > 0);
    if (found.length === 0 && variations.length > 0) {
      tips.push({ severity: 'ok', text: `Try using keyword variations like "${variations.slice(0, 2).join('", "')}" for more natural language.` });
    }
  }

  return tips;
}


// ─────────────────────────────────────────────────────────────────────
// 6. UI RENDERERS
// ─────────────────────────────────────────────────────────────────────

const RING_CIRCUMFERENCE = 2 * Math.PI * 42; // ≈ 263.89

/** Update a circular score gauge with colour from the palette. */
function updateScoreRing(ringEl, labelEl, score) {
  const offset = RING_CIRCUMFERENCE - (score / 100) * RING_CIRCUMFERENCE;
  ringEl.style.strokeDashoffset = offset;

  // Remove old colour classes and apply new one
  ringEl.classList.remove('stroke-green-500', 'stroke-amber-500', 'stroke-red-500', 'stroke-cyan-500');
  if (score >= 70)      ringEl.classList.add('stroke-green-500');
  else if (score >= 40) ringEl.classList.add('stroke-amber-500');
  else                  ringEl.classList.add('stroke-red-500');

  labelEl.textContent = score;
}

/** Render check results into a <ul>. */
function renderChecks(ulEl, checks) {
  ulEl.innerHTML = '';
  for (const c of checks) {
    const li = document.createElement('li');
    li.className = 'flex items-start gap-2 py-1.5 border-b border-gray-100 dark:border-navy-800 last:border-0';

    const dot = document.createElement('span');
    dot.className = 'mt-1 flex-shrink-0 w-2.5 h-2.5 rounded-full';
    if (c.status === 'good')     dot.classList.add('bg-green-500');
    else if (c.status === 'ok')  dot.classList.add('bg-amber-500');
    else                         dot.classList.add('bg-red-500');

    const textDiv = document.createElement('div');
    const strong = document.createElement('strong');
    strong.className = 'block text-xs font-semibold';
    strong.textContent = c.label;
    const detail = document.createElement('span');
    detail.className = 'block text-xs text-gray-500 dark:text-gray-400 mt-0.5';
    detail.textContent = c.detail;
    textDiv.appendChild(strong);
    textDiv.appendChild(detail);

    li.appendChild(dot);
    li.appendChild(textDiv);
    ulEl.appendChild(li);
  }
}

/** Render heading structure tree from HTML headings. */
function renderHeadings(container, headings) {
  container.innerHTML = '';
  if (headings.length === 0) {
    container.innerHTML = '<p class="text-gray-400 italic text-xs">No headings detected yet.</p>';
    return;
  }

  const h1Count = headings.filter(h => h.level === 1).length;
  if (h1Count === 0) {
    const warn = document.createElement('p');
    warn.className = 'text-amber-500 text-xs font-semibold mb-2';
    warn.textContent = 'Warning: No H1 heading found. Every page should have exactly one H1.';
    container.appendChild(warn);
  } else if (h1Count > 1) {
    const warn = document.createElement('p');
    warn.className = 'text-red-500 text-xs font-semibold mb-2';
    warn.textContent = 'Error: Multiple H1 headings found. Use only one H1 per page.';
    container.appendChild(warn);
  }

  let prevLevel = 0;
  let hasSkip = false;
  for (const h of headings) {
    if (h.level > prevLevel + 1 && prevLevel > 0) hasSkip = true;
    prevLevel = h.level;
  }
  if (hasSkip) {
    const warn = document.createElement('p');
    warn.className = 'text-amber-500 text-xs font-semibold mb-2';
    warn.textContent = 'Warning: Heading levels are skipped (e.g. H2 then H4). Keep a logical hierarchy.';
    container.appendChild(warn);
  }

  for (const h of headings) {
    const div = document.createElement('div');
    div.className = 'flex items-center gap-2';
    div.style.paddingLeft = `${(h.level - 1) * 16}px`;

    const badge = document.createElement('span');
    badge.className = 'flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded bg-navy-100 dark:bg-navy-800 text-navy-600 dark:text-cyan-300';
    badge.textContent = `H${h.level}`;

    const text = document.createElement('span');
    text.className = 'text-xs truncate';
    text.textContent = h.text;

    div.appendChild(badge);
    div.appendChild(text);
    container.appendChild(div);
  }
}

/** Render suggestions list. */
function renderSuggestions(ulEl, tips) {
  ulEl.innerHTML = '';
  if (tips.length === 0) {
    ulEl.innerHTML = '<li class="text-green-600 dark:text-green-400 text-xs font-semibold">All looking good! Keep up the great work.</li>';
    return;
  }

  tips.sort((a, b) => (a.severity === 'poor' ? 0 : 1) - (b.severity === 'poor' ? 0 : 1));

  for (const tip of tips) {
    const li = document.createElement('li');
    li.className = 'flex items-start gap-2 py-1.5 border-b border-gray-100 dark:border-navy-800 last:border-0';

    const dot = document.createElement('span');
    dot.className = 'mt-1.5 flex-shrink-0 w-2 h-2 rounded-full';
    dot.classList.add(tip.severity === 'poor' ? 'bg-red-500' : 'bg-amber-400');

    const text = document.createElement('span');
    text.className = 'text-xs text-gray-600 dark:text-gray-300';
    text.textContent = tip.text;

    li.appendChild(dot);
    li.appendChild(text);
    ulEl.appendChild(li);
  }
}


// ─────────────────────────────────────────────────────────────────────
// 7. MAIN ANALYSIS PIPELINE
// ─────────────────────────────────────────────────────────────────────

function runAnalysis() {
  // Get HTML from CKEditor, or fall back to empty string if not ready yet
  const contentHtml  = editorInstance ? editorInstance.getData() : '';
  const contentPlain = htmlToPlainText(contentHtml);
  const keyword      = dom.keyword.value;
  const title        = dom.seoTitle.value;
  const metaDesc     = dom.metaDesc.value;
  const slug         = dom.seoSlug.value;

  // ── Basic stats ────────────────────────────────────────────────────
  const words      = wordCount(contentPlain);
  const chars      = contentPlain.length;
  const paragraphs = getParagraphsFromHtml(contentHtml);
  const sentences  = getSentences(contentPlain);

  dom.wordCount.textContent      = words;
  dom.charCount.textContent      = chars;
  dom.paragraphCount.textContent = paragraphs.length;
  dom.sentenceCount.textContent  = sentences.length;

  // ── Snippet preview (update both desktop and mobile) ────────────
  const displayTitle = title    || 'Your Meta Title';
  const displaySlug  = slug     || 'your-page-slug';
  const displayDesc  = metaDesc || 'Your meta description will appear here. Write a compelling summary to improve click-through rates.';

  // Desktop snippet
  dom.snippetDTitle.textContent = displayTitle;
  dom.snippetDSlug.textContent  = displaySlug;
  dom.snippetDDesc.textContent  = displayDesc;

  // Mobile snippet
  dom.snippetMTitle.textContent = displayTitle;
  dom.snippetMSlug.textContent  = displaySlug;
  dom.snippetMDesc.textContent  = displayDesc;

  dom.seoTitleCount.textContent = `${title.length} / 60`;
  dom.seoTitleCount.className = title.length > 60
    ? 'text-xs text-red-500' : title.length >= 50
    ? 'text-xs text-green-500' : 'text-xs text-gray-400';

  dom.metaDescCount.textContent = `${metaDesc.length} / 160`;
  dom.metaDescCount.className = metaDesc.length > 160
    ? 'text-xs text-red-500' : metaDesc.length >= 120
    ? 'text-xs text-green-500' : 'text-xs text-gray-400';

  // ── SEO checks ─────────────────────────────────────────────────────
  const seoResults = runSeoChecks(contentPlain, contentHtml, keyword, title, metaDesc, slug);
  renderChecks(dom.seoChecks, seoResults);
  const seoScore = computeScore(seoResults);
  updateScoreRing(dom.seoScoreRing, dom.seoScoreLabel, seoScore);

  // ── Readability checks ─────────────────────────────────────────────
  const readResults = runReadabilityChecks(contentPlain, contentHtml);
  renderChecks(dom.readChecks, readResults);
  const readScore = computeScore(readResults);
  updateScoreRing(dom.readScoreRing, dom.readScoreLabel, readScore);

  // ── Heading structure ──────────────────────────────────────────────
  const headings = getHeadingsFromHtml(contentHtml);
  renderHeadings(dom.headingStruct, headings);

  // ── Suggestions ────────────────────────────────────────────────────
  const tips = generateSuggestions(seoResults, readResults, contentPlain, contentHtml, keyword);
  renderSuggestions(dom.suggestions, tips);
}


// ─────────────────────────────────────────────────────────────────────
// 8. EXPORT REPORT AS JSON
// ─────────────────────────────────────────────────────────────────────

function exportReport() {
  const contentHtml  = editorInstance ? editorInstance.getData() : '';
  const contentPlain = htmlToPlainText(contentHtml);
  const keyword  = dom.keyword.value;
  const title    = dom.seoTitle.value;
  const metaDesc = dom.metaDesc.value;
  const slug     = dom.seoSlug.value;
  const words    = wordCount(contentPlain);

  const seoResults  = runSeoChecks(contentPlain, contentHtml, keyword, title, metaDesc, slug);
  const readResults = runReadabilityChecks(contentPlain, contentHtml);

  const report = {
    timestamp: new Date().toISOString(),
    focusKeyword: keyword,
    seoTitle: title,
    slug,
    metaDescription: metaDesc,
    contentStats: {
      words,
      characters: contentPlain.length,
      paragraphs: getParagraphsFromHtml(contentHtml).length,
      sentences: getSentences(contentPlain).length,
      headings: getHeadingsFromHtml(contentHtml),
    },
    seoScore: computeScore(seoResults),
    readabilityScore: computeScore(readResults),
    seoChecks: seoResults,
    readabilityChecks: readResults,
    suggestions: generateSuggestions(seoResults, readResults, contentPlain, contentHtml, keyword),
    fleschReadingEase: words >= 50 ? fleschReadingEase(contentPlain) : null,
  };

  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `seo-report-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}


// ─────────────────────────────────────────────────────────────────────
// 9. DARK MODE
// ─────────────────────────────────────────────────────────────────────

function initDarkMode() {
  const stored = localStorage.getItem('seo-dark-mode');
  if (stored === 'true' || (stored === null && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
  }
}

function toggleDarkMode() {
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('seo-dark-mode', document.documentElement.classList.contains('dark'));
}


// ─────────────────────────────────────────────────────────────────────
// 10. BOOTSTRAP
// ─────────────────────────────────────────────────────────────────────

(function init() {
  initDarkMode();

  // Debounced analysis for non-editor fields
  const analyse = debounce(runAnalysis, 200);
  dom.keyword.addEventListener('input', analyse);
  dom.seoTitle.addEventListener('input', analyse);
  dom.metaDesc.addEventListener('input', analyse);
  dom.seoSlug.addEventListener('input', analyse);

  // Buttons
  dom.btnDarkMode.addEventListener('click', toggleDarkMode);
  dom.btnExport.addEventListener('click', exportReport);

  // Snippet preview tab switching (Desktop / Mobile)
  dom.tabDesktop.addEventListener('click', () => {
    dom.snippetDesktop.classList.remove('hidden');
    dom.snippetMobile.classList.add('hidden');
    dom.tabDesktop.classList.add('snippet-tab-active');
    dom.tabMobile.classList.remove('snippet-tab-active');
  });
  dom.tabMobile.addEventListener('click', () => {
    dom.snippetDesktop.classList.add('hidden');
    dom.snippetMobile.classList.remove('hidden');
    dom.tabMobile.classList.add('snippet-tab-active');
    dom.tabDesktop.classList.remove('snippet-tab-active');
  });

  // Initialise CKEditor (it will wire its own change listener)
  initEditor();
})();
