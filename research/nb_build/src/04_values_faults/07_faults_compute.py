fault_kw = ["исправ", "авар", "неис", "обест", "ошибк", "откл", "демонт",
            "нет связи", "задым", "пожар", "затоп", "отказ", "взлом"]
fault = text[text.index.map(lambda v: any(kw in v.lower() for kw in fault_kw))]
print("Статусы-маркеры неисправностей (кол-во событий за все годы):")
print(fault.to_string())