from services.engine.sector.names import canonical_sector_name


def test_canonical_sector_name_maps_common_moneyflow_industries() -> None:
    assert canonical_sector_name("证券Ⅱ") == "证券"
    assert canonical_sector_name("证券Ⅲ") == "证券"
    assert canonical_sector_name("汽车零部件") == "汽车配件"
    assert canonical_sector_name("其他汽车零部件") == "汽车配件"
    assert canonical_sector_name("化学原料") == "化工原料"
    assert canonical_sector_name("其他化学制品") == "化工原料"
    assert canonical_sector_name("医疗设备") == "医疗保健"
    assert canonical_sector_name("环保设备Ⅱ") == "环境保护"
    assert canonical_sector_name("白酒Ⅱ") == "白酒"
    assert canonical_sector_name("中药Ⅱ") == "中成药"
    assert canonical_sector_name("纺织制造") == "纺织"
    assert canonical_sector_name("出版") == "出版业"
    assert canonical_sector_name("乳品") == "乳制品"
    assert canonical_sector_name("炼油化工") == "石油加工"
    assert canonical_sector_name("电信运营商") == "电信运营"
    assert canonical_sector_name("铁路运输") == "铁路"
    assert canonical_sector_name("旅游及景区") == "旅游景点"
    assert canonical_sector_name("特钢Ⅱ") == "特种钢"
    assert canonical_sector_name("超市") == "超市连锁"
