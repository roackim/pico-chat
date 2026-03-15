import difflib

def split_string(s: str):
    s = s.replace("_", " ")
    s = s.replace("-", " ")
    s = s.strip()
    return s.split(" ")

def fuzzy_score(search_terms: list[str], string: str, word_threshold=0.71):
    """
    Return the number of search terms found in reference string within word_threshold variability.
    """
    score = 0
    
    splitted_string = split_string(string)
    if not splitted_string:
        return 0
        
    for term in search_terms:
        best_match_for_term = 0
        for word in splitted_string:
            res = difflib.SequenceMatcher(None, term, word).ratio()
            if res > best_match_for_term:
                best_match_for_term = res
        
        # Only add to score if it meets the threshold
        if best_match_for_term >= word_threshold:
            score += best_match_for_term
    
    return score

def fuzzy_search(keywords: list[str] | str, list_of_strings: list[str], threshold=0.1, nmax=None):
    assert nmax is None or nmax > 0
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.lower().strip() for k in keywords if k.strip()]
    
    if not keywords:
        return [(s, 1.0) for s in list_of_strings][:nmax]
    
    results = []
    nterms = len(keywords)
    
    for string in list_of_strings:
        score = fuzzy_score(keywords, string.lower().strip())
        # Use a more lenient ratio to capture partial matches like "h" for "help"
        ratio = score / nterms
        if ratio >= threshold or any(k in string.lower() for k in keywords):
            # Boost if contains prefix to favor simple matches
            if any(string.lower().startswith(k) for k in keywords):
                ratio += 0.5
            results.append((string, ratio))
                    
    sorted_results = sorted(results, key=lambda x: x[1], reverse=True)
    
    if nmax is not None and nmax >= len(sorted_results):
        nmax = None
    
    return sorted_results[:nmax]
