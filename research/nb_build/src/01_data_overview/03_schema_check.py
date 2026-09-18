# Заголовки всех лет — проверка одинаковой схемы
for fp in du.journal_files():
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        head, first = f.readline().strip(), f.readline().strip()
    print(f"{fp.name:28s} | {head} | {first[:60]}")

# Пример записей 2026 (первые 3 строки)
df = pd.read_csv(
    du.find_dataset_dir() / "extracted" / "ext-journal-2026.csv",
    dtype=str, nrows=3, on_bad_lines="skip",
)
df.head()