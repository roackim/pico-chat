"""Sample-based regression tests for token estimation heuristics.

These tests port the root-level ``test_samples.py`` script into pytest so they run
with the rest of the suite. The estimator is intentionally heuristic, so we
assert bounded error rather than exact equality.
"""

import pytest

from pico_chat.harness.token_estimation import _calculate_code_ratio, estimate_tokens


SAMPLES = [
    {
        "tag": "code_cpp",
        "sample": """

struct Vec3 { float x, y, z; };
struct GridCell { Vec3 p[8]; float val[8]; };
struct Triangle { Vec3 p[3]; };

// Linear interpolation between two vertices based on isolevel
Vec3 interpolate(Vec3 p1, Vec3 p2, float v1, float v2, float isolevel) {
    if (std::abs(isolevel - v1) < 1e-5) return p1;
    if (std::abs(isolevel - v2) < 1e-5) return p2;
    if (std::abs(v1 - v2) < 1e-5) return p1;
    float mu = (isolevel - v1) / (v2 - v1);
    return { p1.x + mu * (p2.x - p1.x), p1.y + mu * (p2.y - p1.y), p1.z + mu * (p2.z - p1.z) };
}

int polygonize(GridCell cell, float isolevel, Triangle* triangles) {
    int cubeindex = 0;
    if (cell.val[0] < isolevel) cubeindex |= 1;
    if (cell.val[1] < isolevel) cubeindex |= 2;
    if (cell.val[2] < isolevel) cubeindex |= 4;
    if (cell.val[3] < isolevel) cubeindex |= 8;
    if (cell.val[4] < isolevel) cubeindex |= 16;
    if (cell.val[5] < isolevel) cubeindex |= 32;
    if (cell.val[6] < isolevel) cubeindex |= 64;
    if (cell.val[7] < isolevel) cubeindex |= 128;

    // Check if cube is entirely inside or outside the surface
    if (edgeTable[cubeindex] == 0) return 0;

    Vec3 virtlist[12];
    if (edgeTable[cubeindex] & 1) virtlist[0] = interpolate(cell.p[0], cell.p[1], cell.val[0], cell.val[1], isolevel);
    if (edgeTable[cubeindex] & 2) virtlist[1] = interpolate(cell.p[1], cell.p[2], cell.val[1], cell.val[2], isolevel);
    if (edgeTable[cubeindex] & 4) virtlist[2] = interpolate(cell.p[2], cell.p[3], cell.val[2], cell.val[3], isolevel);
    if (edgeTable[cubeindex] & 8) virtlist[3] = interpolate(cell.p[3], cell.p[0], cell.val[3], cell.val[0], isolevel);
    if (edgeTable[cubeindex] & 16) virtlist[4] = interpolate(cell.p[4], cell.p[5], cell.val[4], cell.val[5], isolevel);
    if (edgeTable[cubeindex] & 32) virtlist[5] = interpolate(cell.p[5], cell.p[6], cell.val[5], cell.val[6], isolevel);
    if (edgeTable[cubeindex] & 64) virtlist[6] = interpolate(cell.p[6], cell.p[7], cell.val[6], cell.val[7], isolevel);
    if (edgeTable[cubeindex] & 128) virtlist[7] = interpolate(cell.p[7], cell.p[4], cell.val[7], cell.val[4], isolevel);
    if (edgeTable[cubeindex] & 256) virtlist[8] = interpolate(cell.p[0], cell.p[4], cell.val[0], cell.val[4], isolevel);
    if (edgeTable[cubeindex] & 512) virtlist[9] = interpolate(cell.p[1], cell.p[5], cell.val[1], cell.val[5], isolevel);
    if (edgeTable[cubeindex] & 1024) virtlist[10] = interpolate(cell.p[2], cell.p[6], cell.val[2], cell.val[6], isolevel);
    if (edgeTable[cubeindex] & 2048) virtlist[11] = interpolate(cell.p[3], cell.p[7], cell.val[3], cell.val[7], isolevel);

    int ntri = 0;
    for (int i = 0; triTable[cubeindex][i] != -1; i += 3) {
        triangles[ntri].p[0] = virtlist[triTable[cubeindex][i]];
        triangles[ntri].p[1] = virtlist[triTable[cubeindex][i+1]];
        triangles[ntri].p[2] = virtlist[triTable[cubeindex][i+2]];
        ntri++;
    }
    return ntri;
}

""",
        "token_count": 1078,
        "max_abs_error_pct": 8.0,
    },
    {
        "tag": "text",
        "sample": """
Bees are winged insects that form a monophyletic clade Anthophila within the superfamily Apoidea of the order Hymenoptera, with over 20,000 known species in seven recognized families.[1][2][3] Some species - including honey bees, bumblebees, and stingless bees - are social insects living in highly hierarchical colonies, while over 90% of bee species - including mason bees, carpenter bees, leafcutter bees, and sweat bees - are solitary. Members of the most well-known bee genus, Apis (i.e. honey bees), are known to construct hexagonally celled waxy nests called hives.

Unlike the closely related wasps and ants, who are carnivorous/omnivorous, bees are herbivores that specifically feed on nectar (nectarivory) and pollen (palynivory), the former primarily as a carbohydrate source for metabolic energy, and the latter primarily for protein and other nutrients for their larvae. They are found on every continent except Antarctica, and in every habitat on the planet that contains insect-pollinated flowering plants. The most common bees in the Northern Hemisphere are the Halictidae, or sweat bees, but they are small and often mistaken for wasps or flies. Bees range in size from tiny stingless bee species, whose workers are less than 2 millimeters (0.08 in) long,[4] to the leafcutter bee Megachile pluto, the largest species of bee, whose females can attain a length of 39 millimeters (1.54 in). Vertebrate predators of bees include primates and birds such as bee-eaters; insect predators include beewolves and dragonflies.

Bees are best known for their ecological roles as pollinators and, in the case of the best-known species, the western honey bee, for producing honey, a regurgitated and dehydrated viscous mixture of partially digested monosaccharides kept as food storage of the bee colony. Pollination management via bees is important both ecologically and agriculturally, and the decline in wild bee populations has increased the demand and value of domesticated pollination by commercially managed hives of honey bees. Human beekeeping or apiculture (meliponiculture for stingless bees) has been practiced as a discipline of animal husbandry for millennia, since at least the times of Ancient Egypt and Ancient Greece. Bees have appeared in mythology and folklore, through all phases of art and literature from ancient times to the present day, although primarily focused in the Northern Hemisphere where beekeeping is far more common. In Mesoamerica, the Maya have practiced large-scale intensive meliponiculture since pre-Columbian times.
""",
        "token_count": 569,
        "max_abs_error_pct": 8.0,
    },
    {
        "tag": "code_py",
        "sample": '''
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

''',
        "token_count": 465,
        "max_abs_error_pct": 8.0,
    },
]


@pytest.mark.parametrize("sample", SAMPLES, ids=[sample["tag"] for sample in SAMPLES])
def test_sample_estimation_accuracy_bounds(sample):
    """Estimator should ideally overestimate, but stay within bounded error (-5% to +10%)."""
    estimated = estimate_tokens(sample["sample"])
    actual = sample["token_count"]

    error = estimated - actual
    error_pct = (error / actual) * 100
    
    # We prefer overestimating (safe) but allow a small underestimate margin
    assert -5.0 <= error_pct <= 10.0, f"Error {error_pct:+.1f}% outside acceptable bounds"


def test_sample_suite_aggregate_error():
    """Aggregate error across representative samples should be near zero or slightly positive."""
    total_actual = sum(sample["token_count"] for sample in SAMPLES)
    total_estimated = sum(estimate_tokens(sample["sample"]) for sample in SAMPLES)

    aggregate_error_pct = ((total_estimated - total_actual) / total_actual) * 100
    assert -2.0 <= aggregate_error_pct <= 5.0, f"Total error {aggregate_error_pct:+.1f}% outside bounds"


def test_sample_code_ratio_classification_directionally_correct():
    """Code-like fixture should score higher than prose-like fixture."""
    samples_by_tag = {sample["tag"]: sample for sample in SAMPLES}

    cpp_ratio = _calculate_code_ratio(samples_by_tag["code_cpp"]["sample"])
    text_ratio = _calculate_code_ratio(samples_by_tag["text"]["sample"])
    py_ratio = _calculate_code_ratio(samples_by_tag["code_py"]["sample"])

    assert cpp_ratio > py_ratio > text_ratio
