"""Historical visual designs used to exercise opaque prompt round trips."""

CONTRACTS = {'zh': {'single': ['时代基底', '国家/朝代', '人种', '类型基底', '脸型', '发型', '耳饰', '身材', '头身比', '上身着装', '下身着装', '鞋子', '性别', '年龄'], 'group': ['人物特征', '年龄段', '性别', '种族', '人数规模', '身材', '脸型', '眉毛', '眼镜', '鼻子', '嘴唇', '皮肤', '特殊标记', '发型', '服饰和道具']}, 'en': {'single': ['Era', 'Country/Dynasty', 'Ethnicity/Species', 'World type', 'Face', 'Hair/Fur', 'Ear accessories', 'Build', 'Head-to-body ratio', 'Upper clothing', 'Lower clothing', 'Footwear', 'Gender', 'Age'], 'group': ['Group identity', 'Age range', 'Gender', 'Ethnicity/Species', 'Group size', 'Build', 'Face', 'Eyebrows', 'Eyewear', 'Nose', 'Lips', 'Skin', 'Distinctive marks', 'Hair/Fur', 'Clothing and props']}}

SINGLE_CHARACTER_TRAIT_LABELS = tuple(CONTRACTS["zh"]["single"])
GROUP_PORTRAIT_TRAIT_LABELS = tuple(CONTRACTS["zh"]["group"])


def trait_labels(group=False, language="zh"):
    return tuple(CONTRACTS[language]["group" if group else "single"])
