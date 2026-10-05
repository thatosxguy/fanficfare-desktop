"""Reproducible CPU benchmark; no network requests or private stories."""

import cProfile
import io
import pstats
import re
from statistics import median
import time

from bs4 import BeautifulSoup
from fanficfare_gui.engine import html_word_count


chapter = "<html><body>" + ("<p>One café paragraph with <em>formatted words</em>, don't-stop punctuation &amp; entities.</p>" * 2000) + "<script>ignored words</script><style>ignored styles</style></body></html>"
chapters = [chapter] * 3


def previous_count(chapters):
    total = 0
    for html in chapters:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        total += len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", soup.get_text(" ", strip=True)))
    return total


def measure(function):
    durations = []
    for _ in range(5):
        start = time.perf_counter()
        words = function(chapters)
        durations.append(time.perf_counter() - start)
    return words, median(durations)


old_words, old_time = measure(previous_count)
new_words, new_time = measure(html_word_count)
assert old_words == new_words
print(f"Synthetic chapter text: {old_words:,} words, {sum(map(len, chapters)):,} characters")
print(f"Previous counting: {old_time:.4f}s median (5 runs)")
print(f"Streaming counting: {new_time:.4f}s median (5 runs)")
print(f"Counting speedup: {old_time / new_time:.2f}×")
print("This measures local counting only; it does not predict website download speed.")
profile = cProfile.Profile()
profile.runcall(html_word_count, chapters)
output = io.StringIO()
pstats.Stats(profile, stream=output).sort_stats("cumulative").print_stats(8)
print(output.getvalue())
