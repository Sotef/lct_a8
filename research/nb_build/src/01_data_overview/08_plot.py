import matplotlib.pyplot as plt

fig, ax = plt.subplots(1, 2, figsize=(14, 4))
summary.plot(x="год", y="строк", kind="bar", ax=ax[0], title="Событий по годам")
summary.plot(x="год", y="доля_тревожных_%", kind="bar", ax=ax[1], title="Доля тревог %")
plt.tight_layout()
plt.show()