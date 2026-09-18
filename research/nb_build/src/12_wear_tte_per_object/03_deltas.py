# Парные дельты и сводка
d_uno = df["uno_c_лок"] - df["uno_c_глоб"]
d_ibs = df["ibs_лок"] - df["ibs_глоб"]

print("Uno-C: лок лучше в %.0f%% объектов | mean=%+.3f med=%+.3f" % (
    100 * summ["deltas"]["uno_c_share_local_better"],
    summ["deltas"]["uno_c_mean"], summ["deltas"]["uno_c_med"]))
print("IBS:   лок лучше в %.0f%% объектов | mean=%+.3f med=%+.3f" % (
    100 * summ["deltas"]["ibs_share_local_better"],
    summ["deltas"]["ibs_mean"], summ["deltas"]["ibs_med"]))

winners = df.loc[d_uno > 0]
w = winners.assign(delta=(winners["uno_c_лок"] - winners["uno_c_глоб"]).round(3))
print("\nОбъекты, где локальная заметно лучше (delta Uno-C > +0.01):")
print(w.loc[d_uno[winners.index] > 0.01, ["объект", "n_train", "uno_c_лок", "uno_c_глоб", "delta"]]
      .to_string(index=False))