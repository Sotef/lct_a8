# Калибровка риска «событие <= 30д»: дек или предсказанного риска, O/E.
oe = calibration_oe(S_ho, ho_sub, 30.0)
print(oe.round(3).to_string())

fig, ax = plt.subplots(figsize=(6, 4.5))
ax.plot([0, 1], [0, 1], "--", color="gray")
ax.scatter(oe["pred"], oe["obs"], s=40, color="C1")
ax.set_xlabel("Predicted P(30д)"); ax.set_ylabel("Observed доля событий")
ax.set_title("Калибровка P(событие <= 30д), holdout")
ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()