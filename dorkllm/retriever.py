# DORK Knowledge Retriever Module
# Handles retrieval from the deterministic Aligned Knowledge Base (KB)

import re
from pathlib import Path

KB_PATH = Path("ui/developer/ADAADdev/dork_knowledge_base.js")

def get_kb_matches(query, threshold=0.4):
    """
    Retrieves the best match from the local JS-based knowledge base.
    """
    if not KB_PATH.exists():
        return None

    try:
        kb_text = KB_PATH.read_text()
        matches = []
        # Support both array-based and object-based KB structures found in ADAAD
        kb_match = re.search(r"const KB = \[(.*?)\];", kb_text, re.DOTALL)
        if kb_match:
            kb_content = kb_match.group(1)
            objects = re.findall(r"\{(.*?)\}", kb_content, re.DOTALL)
            for obj in objects:
                k_m = re.search(r"key:\s*['"](.*?)['"]", obj)
                a_m = re.search(r"answer:\s*['"](.*)['"]", obj, re.DOTALL)
                if k_m and a_m:
                    ans = a_m.group(1)
                    # Clean up trailing quotes and escaping
                    actual_ans_match = re.search(r"(.*?)(?<!\\)['"]", ans, re.DOTALL)
                    if actual_ans_match:
                        ans = actual_ans_match.group(1)
                    matches.append({
                        "key": k_m.group(1), 
                        "answer": ans.replace("\'", "'").replace('\"', '"')
                    })
        
        if not matches:
            return None

        query_words = set(re.findall(r'\w+', query.lower()))
        scored_matches = []
        for m in matches:
            key_words = set(re.findall(r'\w+', m["key"].lower()))
            overlap = len(query_words & key_words)
            if overlap > 0:
                score = overlap / len(key_words)
                scored_matches.append((score, m))
        
        if scored_matches:
            best_score, best_match = max(scored_matches, key=lambda x: x[0])
            if best_score > threshold:
                return {
                    "score": best_score,
                    "answer": best_match["answer"],
                    "key": best_match["key"]
                }
    except Exception as e:
        print(f"[-] KB Retrieval Error: {e}")
        
    return None
