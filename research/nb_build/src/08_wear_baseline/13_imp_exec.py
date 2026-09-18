imp = pd.Series(catb.get_feature_importance(), index=X_cols).sort_values(ascending=False)
print(imp.head(15).to_string())