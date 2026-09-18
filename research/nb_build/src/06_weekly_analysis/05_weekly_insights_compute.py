import matplotlib.pyplot as plt

# Топ-15 недель по числу тревог
top_w = weekly.nlargest(15, "тревог")[["год_неделя", "событий", "тревог", "доля_тревог_%"]]
print("Топ-15 недель по тревогам:")
print(top_w.to_string(index=False))

# Среднее по неделям года (сезонная компонента)
season = weekly.groupby("неделя")[["событий", "тревог", "доля_тревог_%"]].mean()
print("\nСредне-недельная картина по номеру недели (1..52):")
print(season.reset_index().sort_values("тревог", ascending=False).head(10).to_string(index=False))