import requests
from scrapy.selector import Selector
from flask import flash
import re
from markupsafe import Markup
from sklearn.feature_extraction.text import TfidfVectorizer
from rake_nltk import Rake
import nltk
from collections import Counter

def extract_text(url, weighted=False):
    """
    Extract all visible text from the given URL using Scrapy's Selector.
    Text within <script> and <style> tags is excluded.
    Prioritizes main content over navigation and footer elements.

    Args:
        url: The URL to extract text from
        weighted: If True, returns weighted text (title/headings repeated for keyword extraction)
                  If False, returns clean text for display
    """
    # Headers to mimic a real browser request (avoid 403 Forbidden errors)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return f"Error fetching URL: {e}"

    sel = Selector(text=resp.text)

    # Extract text with priority weighting
    # High priority: title, meta description, h1-h3, main content
    title = sel.xpath('//title/text()').get() or ""
    meta_desc = sel.xpath('//meta[@name="description"]/@content').get() or ""
    h1_tags = " ".join(sel.xpath('//h1//text()').getall())
    h2_tags = " ".join(sel.xpath('//h2//text()').getall())
    h3_tags = " ".join(sel.xpath('//h3//text()').getall())

    # Try to get main content (common selectors for main content)
    # Exclude meta elements like dates, authors, categories, tags
    main_content = sel.xpath('''
        //main//text()[
            not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and
            not(ancestor::*[@class="post-meta"]) and not(ancestor::*[@class="entry-meta"]) and
            not(ancestor::*[@class="post-date"]) and not(ancestor::*[@class="entry-date"]) and
            not(ancestor::*[@class="post-author"]) and not(ancestor::*[@class="entry-author"]) and
            not(ancestor::*[@class="post-categories"]) and not(ancestor::*[@class="post-tags"]) and
            not(ancestor::time) and not(ancestor::*[@class="meta"]) and not(ancestor::*[@class="byline"])
        ] |
        //article//text()[
            not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and
            not(ancestor::*[@class="post-meta"]) and not(ancestor::*[@class="entry-meta"]) and
            not(ancestor::*[@class="post-date"]) and not(ancestor::*[@class="entry-date"]) and
            not(ancestor::*[@class="post-author"]) and not(ancestor::*[@class="entry-author"]) and
            not(ancestor::*[@class="post-categories"]) and not(ancestor::*[@class="post-tags"]) and
            not(ancestor::time) and not(ancestor::*[@class="meta"]) and not(ancestor::*[@class="byline"])
        ] |
        //*[@id="content"]//text()[
            not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and
            not(ancestor::*[@class="post-meta"]) and not(ancestor::*[@class="entry-meta"]) and
            not(ancestor::time) and not(ancestor::*[@class="meta"])
        ] |
        //*[@class="content"]//text()[
            not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and
            not(ancestor::*[@class="post-meta"]) and not(ancestor::*[@class="entry-meta"]) and
            not(ancestor::time) and not(ancestor::*[@class="meta"])
        ] |
        //*[@class="post-content"]//text()[
            not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and
            not(ancestor::*[@class="post-meta"]) and not(ancestor::*[@class="entry-meta"]) and
            not(ancestor::time) and not(ancestor::*[@class="meta"])
        ] |
        //*[@class="entry-content"]//text()[
            not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and
            not(ancestor::*[@class="post-meta"]) and not(ancestor::*[@class="entry-meta"]) and
            not(ancestor::time) and not(ancestor::*[@class="meta"])
        ]
    ''').getall()

    # If main content extraction failed, fall back to body text (excluding nav and footer)
    if not main_content or len(main_content) < 50:
        main_content = sel.xpath('''
            //body//text()[
                not(ancestor::script) and
                not(ancestor::style) and
                not(ancestor::nav) and
                not(ancestor::footer) and
                not(ancestor::header[@class="site-header"]) and
                not(ancestor::*[@id="sidebar"]) and
                not(ancestor::aside)
            ]
        ''').getall()

    main_text = " ".join(t.strip() for t in main_content if t.strip())

    # Clean text: remove date patterns and metadata
    # Remove date patterns like "November 4, 2023", "Nov 4", "2023-11-04", etc.
    import re
    date_patterns = [
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{0,4}\b',
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s*\d{0,4}\b',
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
        r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',
        r'\bPosted on:?\s*\b',
        r'\bPublished:?\s*\b',
        r'\bUpdated:?\s*\b',
        r'\bBy:?\s+[\w\s]+\b',
        r'\bAuthor:?\s+[\w\s]+\b',
        r'\b\d+\s+min(?:utes?)?\s+read\b',
        r'\bDiet:?\s*\w*\b'
    ]

    for pattern in date_patterns:
        main_text = re.sub(pattern, '', main_text, flags=re.IGNORECASE)
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        h1_tags = re.sub(pattern, '', h1_tags, flags=re.IGNORECASE)
        h2_tags = re.sub(pattern, '', h2_tags, flags=re.IGNORECASE)

    if weighted:
        # Combine with higher weight for important elements
        # Repeat title and headings to increase their importance in keyword extraction
        weighted_text = f"{title} {title} {title} {meta_desc} {meta_desc} {h1_tags} {h1_tags} {h2_tags} {h3_tags} {main_text}"
        return weighted_text.strip()
    else:
        # Return clean text for display (no repetition)
        clean_text = f"{title} {meta_desc} {h1_tags} {h2_tags} {h3_tags} {main_text}"
        return clean_text.strip()

def process_keywords(text, keywords):
    """
    Given the full extracted text and a list of keywords,
    returns a dictionary with the total word count and, for each keyword,
    the count and density (percentage).
    
    Now modified to only count exact word matches.
    """
    results = {}
    words = text.split()
    total_words = len(words)
    
    for keyword in keywords:
        # Use word boundaries to find exact matches only
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        # Find all matches in the text
        matches = re.findall(pattern, text.lower())
        count = len(matches)
        
        # Calculate density
        density = (count * 100 / total_words) if total_words > 0 else 0
        results[keyword] = {'count': count, 'density': density}
        
    return {'total_words': total_words, 'keywords': results}

def correct_text(text):
    """
    Dummy function to simulate correction of the extracted text.
    In a real implementation, you might call an external API.
    """
    corrected = text.replace('mistaekn', 'mistaken')
    return {'original': text, 'corrected': corrected}

def highlight_keywords(text, keywords_colors):
    """
    Wrap each occurrence of each keyword (case-insensitive) in the text with a <span> tag
    that styles it with the specified color and bold font.
    The matched text preserves its original case.

    Modified to only highlight exact word matches.
    """
    highlighted = text
    for keyword, color in keywords_colors.items():
        # Use word boundary markers to match exact words only
        pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
        highlighted = pattern.sub(
            lambda m: f'<span style="color: {color}; font-weight: bold;">{m.group(0)}</span>',
            highlighted
        )
    return Markup(highlighted)

def extract_keywords_tfidf(text, max_keywords=10):
    """
    Extract keywords using TF-IDF (Term Frequency-Inverse Document Frequency) algorithm.
    Returns a list of tuples containing (keyword, score).

    TF-IDF measures how important a word is to a document in a collection.
    It increases proportionally to the number of times a word appears in the document
    but is offset by the frequency of the word across all documents.
    """
    try:
        # Validate input
        if not text or len(text.strip()) < 10:
            print("Text too short for TF-IDF extraction")
            return []

        # Download stopwords if not already downloaded
        try:
            nltk.data.find('corpora/stopwords')
        except LookupError:
            print("Downloading NLTK stopwords...")
            nltk.download('stopwords', quiet=True)

        from nltk.corpus import stopwords
        stop_words = set(stopwords.words('english'))

        # Add custom stopwords for generic web phrases and UI elements
        custom_stop_phrases = {
            # Generic web/navigation
            'click here', 'read more', 'learn more', 'contact us', 'about us',
            'privacy policy', 'terms conditions', 'terms service', 'cookie policy',
            'home page', 'site map', 'follow us', 'social media', 'sign up',
            'log in', 'get started', 'find out', 'make sure', 'want know',
            'need know', 'related posts', 'recent posts', 'leave comment',
            'post navigation', 'search results', 'subscribe newsletter', 'email address',
            'share post', 'leave reply', 'written by', 'posted by', 'published by',
            'updated on', 'posted on', 'last updated', 'read time', 'min read', 'posted in',
            # E-commerce UI elements
            'view cart', 'add cart', 'quick view', 'view details', 'shop now', 'buy now',
            'view product', 'get quote', 'view similar', 'similar products', 'view all',
            'show all', 'load more', 'see more', 'see all', 'show more', 'view more',
            'add wishlist', 'add favorites', 'select size', 'select color', 'choose size',
            'choose color', 'size guide', 'size chart', 'delivery options', 'payment options',
            'return policy', 'shipping info', 'product details', 'product description',
            'customer reviews', 'write review', 'submit review', 'ask question',
            'free shipping', 'free delivery', 'cash delivery', 'secure checkout',
            'proceed checkout', 'continue shopping', 'add bag', 'remove item',
            'update cart', 'apply coupon', 'use code', 'discount code', 'promo code',
            'out stock', 'stock', 'available sizes', 'available colors', 'notify me',
            'back stock', 'pre order', 'order now', 'reserve now', 'book now',
            'compare products', 'recently viewed', 'recommended products', 'you may',
            'customers also', 'frequently bought', 'bought together', 'related items',
            'similar items', 'same category', 'more from', 'explore more', 'discover more',
            # Common UI patterns
            'view', 'select', 'choose', 'add', 'remove', 'update', 'edit', 'delete',
            'submit', 'cancel', 'confirm', 'apply', 'reset', 'clear', 'save',
            'close', 'open', 'expand', 'collapse', 'show', 'hide', 'toggle',
            'next', 'previous', 'back', 'forward', 'home', 'menu', 'search'
        }

        # Month names to filter out date-related phrases
        months = {'january', 'february', 'march', 'april', 'may', 'june',
                  'july', 'august', 'september', 'october', 'november', 'december',
                  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec'}

        # Split text into sentences to create a mini-corpus
        sentences = text.split('.')
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

        if len(sentences) < 2:
            # If we don't have enough sentences, use word frequency instead
            return extract_keywords_frequency(text, max_keywords)

        # Create TF-IDF vectorizer - ONLY multi-word phrases (2-3 words)
        vectorizer = TfidfVectorizer(
            max_features=max_keywords * 10,  # Get more features initially for better filtering
            stop_words=list(stop_words),
            ngram_range=(2, 3),  # ONLY bigrams and trigrams (2-3 words)
            min_df=1,
            max_df=0.7,  # Ignore terms that appear in more than 70% of documents
            lowercase=True,
            token_pattern=r'(?u)\b[a-zA-Z][a-zA-Z]+\b'  # Only alphabetic tokens
        )

        # Fit and transform the sentences
        tfidf_matrix = vectorizer.fit_transform(sentences)

        # Get feature names (keywords)
        feature_names = vectorizer.get_feature_names_out()

        # Sum TF-IDF scores across all sentences
        tfidf_scores = tfidf_matrix.sum(axis=0).A1

        # Create keyword-score pairs and sort by score
        keyword_scores = list(zip(feature_names, tfidf_scores))
        keyword_scores.sort(key=lambda x: x[1], reverse=True)

        # Filter: only multi-word keywords (2+ words) with non-zero scores
        # Exclude generic web phrases, dates, numbers, and non-meaningful content
        result = []
        for kw, score in keyword_scores:
            word_count = len(kw.split())
            kw_lower = kw.lower()
            words = kw_lower.split()

            # Skip if it's a generic phrase
            if kw_lower in custom_stop_phrases:
                continue

            # Skip if contains month names (date-related)
            if any(month in kw_lower for month in months):
                continue

            # Skip if contains numbers or years
            if re.search(r'\d', kw_lower):
                continue

            # Skip if all words are common stop words
            if all(word in stop_words for word in words):
                continue

            # Skip single-letter words or very short phrases
            if any(len(word) <= 2 for word in words):
                continue

            # Only include if has at least one meaningful word (5+ letters for better quality)
            if not any(len(word) >= 5 for word in words):
                continue

            # Skip UI action words
            ui_action_words = {'view', 'select', 'choose', 'click', 'add', 'remove',
                             'buy', 'shop', 'cart', 'checkout', 'login', 'signup',
                             'subscribe', 'follow', 'share', 'like', 'comment', 'review'}
            if any(ui_word in kw_lower for ui_word in ui_action_words):
                continue

            # Skip if contains common category/tag words or metadata terms
            meta_words = ['category', 'categories', 'tags', 'tagged', 'filed', 'archive',
                         'diet', 'comment', 'comments', 'author', 'posted', 'published',
                         'updated', 'share', 'tweet', 'pin', 'email']
            if any(meta_word in kw_lower for meta_word in meta_words):
                continue

            # Skip phrases that are mostly prepositions or articles
            filler_words = {'the', 'and', 'for', 'with', 'this', 'that', 'from', 'into', 'onto', 'upon'}
            word_set = set(words)
            if len(word_set.intersection(filler_words)) == len(words):
                continue

            if score > 0 and word_count >= 2:
                result.append((kw, score))

            if len(result) >= max_keywords:
                break

        print(f"TF-IDF extracted {len(result)} content-specific multi-word keywords")
        return result

    except Exception as e:
        print(f"Error in TF-IDF extraction: {e}")
        import traceback
        traceback.print_exc()
        return []

def extract_keywords_frequency(text, max_keywords=10):
    """
    Fallback method: Extract multi-word keywords based on simple frequency analysis.
    """
    try:
        from nltk.corpus import stopwords
        stop_words = set(stopwords.words('english'))

        # Extract bigrams and trigrams
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        words = [w for w in words if w not in stop_words]

        # Create bigrams
        bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1)]

        # Create trigrams
        trigrams = [f"{words[i]} {words[i+1]} {words[i+2]}" for i in range(len(words)-2)]

        # Combine and count
        phrases = bigrams + trigrams
        phrase_freq = Counter(phrases)

        # Get most common phrases
        most_common = phrase_freq.most_common(max_keywords)

        # Normalize scores
        if most_common:
            max_freq = most_common[0][1]
            return [(phrase, freq / max_freq) for phrase, freq in most_common]

        return []
    except Exception as e:
        print(f"Error in frequency extraction: {e}")
        return []

def extract_keywords_rake(text, max_keywords=10):
    """
    Extract keywords using RAKE (Rapid Automatic Keyword Extraction) algorithm.
    Returns a list of tuples containing (keyword, score).

    RAKE extracts keywords by analyzing word frequency and co-occurrence.
    It identifies phrases (multi-word keywords) that appear frequently and
    calculates a score based on word degree and frequency.
    """
    try:
        # Validate input
        if not text or len(text.strip()) < 10:
            print("Text too short for RAKE extraction")
            return []

        # Download stopwords if not already downloaded
        try:
            nltk.data.find('corpora/stopwords')
        except LookupError:
            print("Downloading NLTK stopwords for RAKE...")
            nltk.download('stopwords', quiet=True)

        try:
            nltk.data.find('tokenizers/punkt_tab')
        except LookupError:
            print("Downloading NLTK punkt_tab tokenizer...")
            nltk.download('punkt_tab', quiet=True)

        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            print("Downloading NLTK punkt tokenizer...")
            nltk.download('punkt', quiet=True)

        # Generic web phrases and UI elements to exclude
        generic_phrases = {
            # Generic web/navigation
            'click here', 'read more', 'learn more', 'contact us', 'about us',
            'privacy policy', 'terms conditions', 'terms service', 'cookie policy',
            'home page', 'site map', 'follow us', 'social media', 'sign up',
            'log in', 'get started', 'find out', 'make sure', 'want know',
            'need know', 'related posts', 'recent posts', 'leave comment',
            'post navigation', 'search results', 'subscribe newsletter', 'email address',
            'share post', 'leave reply', 'back home', 'main menu', 'footer menu',
            'copyright reserved', 'rights reserved', 'powered wordpress', 'built wordpress',
            'page found', 'error occurred', 'try again', 'go back', 'return home',
            'written by', 'posted by', 'published by', 'updated on', 'posted on',
            'last updated', 'read time', 'min read', 'posted in',
            # E-commerce UI elements
            'view cart', 'add cart', 'quick view', 'view details', 'shop now', 'buy now',
            'view product', 'get quote', 'view similar', 'similar products', 'view all',
            'show all', 'load more', 'see more', 'see all', 'show more', 'view more',
            'add wishlist', 'add favorites', 'select size', 'select color', 'choose size',
            'choose color', 'size guide', 'size chart', 'delivery options', 'payment options',
            'return policy', 'shipping info', 'product details', 'product description',
            'customer reviews', 'write review', 'submit review', 'ask question',
            'free shipping', 'free delivery', 'cash delivery', 'secure checkout',
            'proceed checkout', 'continue shopping', 'add bag', 'remove item',
            'update cart', 'apply coupon', 'use code', 'discount code', 'promo code',
            'out stock', 'stock', 'available sizes', 'available colors', 'notify me',
            'back stock', 'pre order', 'order now', 'reserve now', 'book now',
            'compare products', 'recently viewed', 'recommended products', 'you may',
            'customers also', 'frequently bought', 'bought together', 'related items',
            'similar items', 'same category', 'more from', 'explore more', 'discover more'
        }

        # Month names to filter out date-related phrases
        months = {'january', 'february', 'march', 'april', 'may', 'june',
                  'july', 'august', 'september', 'october', 'november', 'december',
                  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec'}

        # Initialize RAKE with max phrase length of 3 words
        rake = Rake(max_length=3, min_length=2)

        # Extract keywords
        rake.extract_keywords_from_text(text)

        # Get ranked keywords with scores
        ranked_keywords = rake.get_ranked_phrases_with_scores()

        if not ranked_keywords:
            print("RAKE found no keywords")
            return []

        # Filter: only include phrases with 2-3 words (NO single words, no long paragraphs)
        # Exclude generic web phrases, dates, numbers, and non-meaningful content
        keyword_scores = []
        for score, phrase in ranked_keywords:
            # Count words in phrase
            words = phrase.split()
            word_count = len(words)
            phrase_lower = phrase.lower()

            # Skip generic phrases
            if phrase_lower in generic_phrases:
                continue

            # Skip if contains month names (date-related)
            if any(month in phrase_lower for month in months):
                continue

            # Skip if contains numbers or years
            if re.search(r'\d', phrase_lower):
                continue

            # Skip phrases that are likely navigation or UI elements
            ui_indicators = ['menu', 'navigation', 'sidebar', 'widget', 'footer', 'header',
                           'view', 'select', 'choose', 'add', 'buy', 'shop', 'cart',
                           'wishlist', 'compare', 'filter', 'sort', 'login', 'signup',
                           'subscribe', 'follow', 'share', 'like', 'comment']
            if any(ui_word in phrase_lower for ui_word in ui_indicators):
                continue

            # Skip single-letter words or very short phrases
            if any(len(word) <= 2 for word in words):
                continue

            # Only include if has at least one meaningful word (5+ letters for better quality)
            if not any(len(word) >= 5 for word in words):
                continue

            # Skip if contains common category/tag words or metadata terms
            meta_words = ['category', 'categories', 'tags', 'tagged', 'filed', 'archive',
                         'diet', 'comment', 'comments', 'author', 'posted', 'published',
                         'updated', 'share', 'tweet', 'pin', 'email']
            if any(meta_word in phrase_lower for meta_word in meta_words):
                continue

            # Skip UI action words
            ui_action_words = {'view', 'select', 'choose', 'click', 'add', 'remove',
                             'buy', 'shop', 'cart', 'checkout', 'login', 'signup',
                             'subscribe', 'follow', 'share', 'like', 'comment', 'review'}
            if any(ui_word in phrase_lower for ui_word in ui_action_words):
                continue

            # Skip phrases that are mostly prepositions or articles
            filler_words = {'the', 'and', 'for', 'with', 'this', 'that', 'from', 'into', 'onto', 'upon'}
            word_set = set(words)
            if len(word_set.intersection(filler_words)) == len(words):
                continue

            # Only include if score > 0 and phrase has 2-3 words (multi-word only)
            if score > 0 and 2 <= word_count <= 3:
                keyword_scores.append((phrase, score))

            if len(keyword_scores) >= max_keywords:
                break

        print(f"RAKE extracted {len(keyword_scores)} content-specific multi-word keywords")
        return keyword_scores

    except Exception as e:
        print(f"Error in RAKE extraction: {e}")
        import traceback
        traceback.print_exc()
        return []

def extract_keywords_combined(text, max_keywords=10, source_text=None):
    """
    Extract keywords using both TF-IDF and RAKE algorithms and combine results.
    Returns a dictionary with both methods' results and a combined ranking.

    Args:
        text: The text to extract keywords from (can be weighted)
        max_keywords: Maximum number of keywords to extract
        source_text: The original source text to verify keywords exist in (if different from text)
    """
    try:
        # Validate input
        if not text or len(text.strip()) < 10:
            print("Text too short for keyword extraction")
            return {
                'tfidf': [],
                'rake': [],
                'combined': []
            }

        print(f"Extracting keywords from text of length: {len(text)}")

        # If source_text is provided, use it for validation
        validation_text = source_text.lower() if source_text else text.lower()

        # Get keywords from both algorithms
        tfidf_keywords = extract_keywords_tfidf(text, max_keywords * 2)  # Get more initially
        rake_keywords = extract_keywords_rake(text, max_keywords * 2)  # Get more initially

        # Validate that keywords actually exist in the source text
        validated_tfidf = []
        for keyword, score in tfidf_keywords:
            if keyword.lower() in validation_text:
                validated_tfidf.append((keyword, score))
            else:
                print(f"Filtered out TF-IDF keyword not in text: '{keyword}'")

        validated_rake = []
        for keyword, score in rake_keywords:
            if keyword.lower() in validation_text:
                validated_rake.append((keyword, score))
            else:
                print(f"Filtered out RAKE keyword not in text: '{keyword}'")

        # Limit to max_keywords after validation
        tfidf_keywords = validated_tfidf[:max_keywords]
        rake_keywords = validated_rake[:max_keywords]

        print(f"TF-IDF returned {len(tfidf_keywords)} validated keywords")
        print(f"RAKE returned {len(rake_keywords)} validated keywords")

        # Create a combined score by normalizing and averaging both methods
        combined_scores = {}

        # Normalize TF-IDF scores
        if tfidf_keywords:
            max_tfidf = max(score for _, score in tfidf_keywords) if tfidf_keywords else 1
            for keyword, score in tfidf_keywords:
                # Only include multi-word keywords (2+ words)
                if len(keyword.split()) >= 2:
                    normalized_score = score / max_tfidf if max_tfidf > 0 else 0
                    combined_scores[keyword.lower()] = combined_scores.get(keyword.lower(), 0) + normalized_score

        # Normalize RAKE scores
        if rake_keywords:
            max_rake = max(score for _, score in rake_keywords) if rake_keywords else 1
            for keyword, score in rake_keywords:
                # Only include multi-word keywords (2+ words)
                if len(keyword.split()) >= 2:
                    normalized_score = score / max_rake if max_rake > 0 else 0
                    combined_scores[keyword.lower()] = combined_scores.get(keyword.lower(), 0) + normalized_score

        # Sort by combined score and validate they exist in source text
        sorted_combined = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)

        # Final validation: ensure combined keywords exist in source text
        validated_combined = []
        for keyword, score in sorted_combined:
            if keyword in validation_text:
                validated_combined.append((keyword, score))
            else:
                print(f"Filtered out combined keyword not in text: '{keyword}'")

            if len(validated_combined) >= max_keywords:
                break

        combined_keywords = validated_combined

        print(f"Combined: {len(combined_keywords)} validated multi-word keywords")

        result = {
            'tfidf': tfidf_keywords,
            'rake': rake_keywords,
            'combined': combined_keywords
        }

        # If no keywords found at all, use frequency fallback for combined
        if not combined_keywords and not tfidf_keywords and not rake_keywords:
            print("No keywords from algorithms, using frequency fallback")
            freq_keywords = extract_keywords_frequency(text, max_keywords)
            result['combined'] = freq_keywords
            result['tfidf'] = freq_keywords
            result['rake'] = freq_keywords

        return result

    except Exception as e:
        print(f"Error in combined keyword extraction: {e}")
        import traceback
        traceback.print_exc()
        return {
            'tfidf': [],
            'rake': [],
            'combined': []
        }
