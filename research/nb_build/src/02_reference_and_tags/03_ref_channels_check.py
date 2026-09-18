ref_ch = du.load_ref_channels()
print("Справочник каналов:", ref_ch.shape)
ref_ch.head()

print("\nТипы датчиков (топ-19):")
print(ref_ch["тип_датчика"].value_counts().to_string())

print("\nИнженерные подсистемы:")
print(ref_ch["тип_инж_системы"].value_counts().to_string())