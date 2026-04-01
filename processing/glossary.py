import json
import os
import re
from difflib import SequenceMatcher

DEFAULT_GLOSSARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "technical_glossary.json"
)
FUZZY_THRESHOLD = 0.80


class GlossaryProcessor:
    def __init__(self, glossary_path: str = DEFAULT_GLOSSARY_PATH):
        self.data = self._load(glossary_path)
        self.keys = list(self.data.keys())
        self.compiled_rules = self._compile_rules()

    def _load(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _compile_rules(self) -> list:
        rules = []
        for correct_word, data in self.data.items():
            aliases = data.get("aliases", [])
            live_replace = data.get("live_replace", False)
            if not aliases:
                continue
            aliases.sort(key=len, reverse=True)
            pattern_str = r"(?i)\b(" + "|".join(map(re.escape, aliases)) + r")\b"
            rules.append((re.compile(pattern_str), correct_word, live_replace))
        return rules

    def apply_live_corrections(self, text: str) -> str:
        if not text:
            return ""
        clean = self._fix_versions(text)
        for pattern, correct, do_replace in self.compiled_rules:
            if do_replace:
                clean = pattern.sub(correct, clean)
        return clean

    def generate_ai_suggestions(self, text: str) -> list[str]:
        if not text:
            return []
        suggestions = []
        seen = set()

        version_matches = re.findall(r"(?i)\b[bB]\s?[\-]?\s?(\d+)\b", text)
        for num in set(version_matches):
            cid = f"VER_{num}"
            if cid not in seen:
                suggestions.append(
                    f"- Se detectó 'b {num}' (o similar): Posiblemente sea 'v{num}'."
                )
                seen.add(cid)

        for pattern, correct, _ in self.compiled_rules:
            if pattern.search(text):
                cid = f"TERM_{correct.upper()}"
                if cid not in seen:
                    suggestions.append(
                        f"- Se detectó término similar a '{correct}' (según diccionario)."
                    )
                    seen.add(cid)

        fuzzy_hits = self._fuzzy_scan(text)
        for bad, correct in fuzzy_hits:
            cid = f"TERM_{correct.upper()}"
            if cid not in seen:
                suggestions.append(
                    f"- Se detectó '{bad}': Fonéticamente similar a '{correct}'."
                )
                seen.add(cid)

        return suggestions

    def _fix_versions(self, text: str) -> str:
        return re.sub(r"(?i)\b[bB]\s?[\-]?\s?(\d+)\b", r"v\1", text)

    def _fuzzy_scan(self, text: str) -> set[tuple[str, str]]:
        matches = set()
        words = re.findall(r"\b[a-zA-Záéíóúñ]{4,}\b", text)
        seen_words = set()
        unique_words = []
        for w in words:
            low = w.lower()
            if low not in seen_words:
                seen_words.add(low)
                unique_words.append(w)
        for word in unique_words[:100]:
            for key in self.keys:
                if word.lower() == key.lower():
                    continue
                if (
                    SequenceMatcher(None, word.lower(), key.lower()).ratio()
                    >= FUZZY_THRESHOLD
                ):
                    matches.add((word, key))
        return matches
