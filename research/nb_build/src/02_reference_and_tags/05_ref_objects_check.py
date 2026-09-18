ref_obj = du.load_ref_objects()
print("Справочник объектов:", ref_obj.shape)
ref_obj.head(10)

print("\nВиды объектов:")
print(ref_obj["вид_объекта"].value_counts().to_string())