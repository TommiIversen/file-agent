"""Temporary script to remove emojis from Python source files."""
import pathlib
import re

# Match emoji characters (single or consecutive)
emoji_pattern = re.compile(
    r'[\U0001F300-\U0001FAFF'
    r'\U00002600-\U000027BF'
    r'\U0000FE00-\U0000FE0F'
    r'\U0000200D'
    r'\U00002702-\U000027B0'
    r'\U0000231A-\U0000231B'
    r'\U000023E9-\U000023F3'
    r'\U000023F8-\U000023FA'
    r'\U00002934-\U00002935'
    r'\U000025AA-\U000025AB'
    r'\U000025B6\U000025C0'
    r'\U000025FB-\U000025FE'
    r'\U00002B05-\U00002B07'
    r'\U00002B1B-\U00002B1C'
    r'\U00002B50\U00002B55'
    r'\U0000203C\U00002049'
    r'\U00002328'
    r'\U000023CF'
    r'\U0001F000-\U0001F02F'
    r'\U0001F0A0-\U0001F0FF'
    r']+'
)

count = 0
for p in sorted(pathlib.Path('app').rglob('*.py')):
    text = p.read_text(encoding='utf-8')
    new_text = emoji_pattern.sub('', text)
    # Only collapse double-spaces between non-whitespace chars (not indentation)
    new_text = re.sub(r'(?<=\S)  (?=\S)', ' ', new_text)
    if text != new_text:
        p.write_text(new_text, encoding='utf-8')
        old_lines = text.splitlines()
        new_lines = new_text.splitlines()
        changed = sum(1 for a, b in zip(old_lines, new_lines) if a != b)
        count += changed
        print(f'  {p}: {changed} lines cleaned')

print(f'\nTotal: {count} lines cleaned')
