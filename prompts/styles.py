"""视觉风格提示词注册表。

每个风格提供两套提示词：
- image_prompt：生图定调 —— 静态画面的材质、光影、色彩与细节要求；
- video_prompt：生视频定调 —— 运动规律、镜头衔接、一致性与时间连续性要求。

本模块仅负责模板与纯渲染函数；业务上下文加载与调用由对应 Service 完成。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StylePromptSet:
    key: str
    label: str
    image_prompt: str
    video_prompt: str


STYLE_PROMPTS: dict[str, StylePromptSet] = {
    style.key: style
    for style in (
        StylePromptSet(
            key="realistic-general",
            label="写实通用",
            image_prompt=(
                "画面采用高度写实的摄影质感：真实皮肤肌理、自然布料褶皱与环境材质的细微颗粒；"
                "光影遵循自然物理规律，柔和高光与清晰阴影层次；色彩真实克制，杜绝滤镜感；"
                "人物五官、比例与透视严格符合现实，细节密度达到照片级。"
            ),
            video_prompt=(
                "镜头语言写实自然：人物动作符合真实物理与惯性，运动连续不跳帧；"
                "手持或稳定器质感均可，但同一场景内保持一致；环境光影随镜头运动连续变化；"
                "禁止卡通化形变、液体金属或非物理特效。"
            ),
        ),
        StylePromptSet(
            key="realistic-urban",
            label="写实都市",
            image_prompt=(
                "现代都市写实风格：玻璃幕墙、沥青街道与霓虹标识的材质真实可信；"
                "城市空气透视与夜景光晕层次丰富；人物着当代都市服装，画面带轻微纪录片质感；"
                "色彩以都市中性色为基底，点缀真实霓虹与车灯光斑。"
            ),
            video_prompt=(
                "都市氛围的运动质感：车流、人流与反光水面连续运动；浅景深跟焦自然呼吸；"
                "镜头可手持跟拍或轨道平移，避免过度戏剧化的炫光；所有反光与阴影随运动一致。"
            ),
        ),
        StylePromptSet(
            key="realistic-cinematic",
            label="写实电影感",
            image_prompt=(
                "电影级写实画面：模拟高端电影镜头的光学特性，浅景深与柔和焦外；"
                "戏剧化但可信的布光，明确的主光方向与轮廓光；色彩经过电影调色，冷暖对比统一；"
                "画幅质感如电影剧照，细节与皮肤质感真实。"
            ),
            video_prompt=(
                "电影级运镜：缓慢推拉、摇移与手持呼吸感；运动模糊符合快门物理；"
                "景深变化与焦点转移平滑；光影随时间自然流动，调色在全片中保持一致；"
                "动作具有重量感与真实节奏。"
            ),
        ),
        StylePromptSet(
            key="anime-japanese",
            label="2D日漫",
            image_prompt=(
                "2D 日本动画风格：清晰的赛璐璐勾线，边缘干净利落；平涂色块配合局部渐变阴影；"
                "人物比例遵循日式动画审美，大眼与符号化表情；背景采用日系动画分层色稿；"
                "色彩明亮通透，高光与腮红点缀到位。"
            ),
            video_prompt=(
                "2D 日式动画运动规律：关键帧动画质感，动作节奏分明、预备与跟随动作明确；"
                "镜头运动以平移、推拉与分镜切换为主；线条抖动与描边保持一致粗细；"
                "色块平涂无渐变涂抹感，口型与表情符号化自然。"
            ),
        ),
        StylePromptSet(
            key="manhwa-urban",
            label="2D韩漫都市",
            image_prompt=(
                "韩国都市条漫风格：精致细腻的数字插画线条，人物比例修长，五官精致立体；"
                "都市背景以现代建筑与时尚街区为主；上色为柔和高饱和数字色，"
                "高光与皮肤光泽细腻，整体带高级时尚杂志感。"
            ),
            video_prompt=(
                "韩漫风格动态：轻量 2D 动画，人物动作流畅优雅、表情细腻；"
                "镜头多用推拉与环绕展示人物；服饰与发丝有轻微物理摆动；"
                "色彩光泽稳定，避免粗糙形变与跳色。"
            ),
        ),
        StylePromptSet(
            key="chinese-3d",
            label="3D国风",
            image_prompt=(
                "3D 国风动画质感：PBR 材质渲染，服饰绸缎、金属与木质纹理真实；"
                "人物建模精致，东方五官与古典发髻；场景为中国古建筑、山水庭院；"
                "光影柔和层次分明，色彩以朱砂、黛青、鎏金等传统色系为主。"
            ),
            video_prompt=(
                "3D 国风镜头：稳定平滑的运镜，人物动作兼具舞蹈韵律与真实重量；"
                "衣袂与发丝使用布料与毛发解算，飘动自然；粒子点缀（花瓣、尘雾）克制；"
                "渲染光保持一致，禁止角色比例崩坏。"
            ),
        ),
        StylePromptSet(
            key="xianxia-3d",
            label="3D仙侠",
            image_prompt=(
                "3D 仙侠风格：宏大的仙山云海与浮空建筑场景；人物仙风道骨，"
                "纱衣与法器细节丰富；特效光晕（灵气、剑光、阵法）晶莹通透；"
                "色彩以青白、紫金为主，光影带仙气朦胧感。"
            ),
            video_prompt=(
                "仙侠特效运动：御剑飞行、法术释放轨迹流畅，粒子与光效层层展开；"
                "运镜多大气升降与环绕，云雾缓慢流动；人物动作飘逸，衣袂翻飞自然；"
                "特效亮度稳定不闪烁，保持东方仙侠美学。"
            ),
        ),
        StylePromptSet(
            key="manhwa-2d",
            label="2D韩漫",
            image_prompt=(
                "2D 韩漫插画风格：细腻的数码线稿与柔和渐变上色；人物比例修长、"
                "五官精致，眼睛层次丰富；服饰现代时尚，材质光泽细腻；"
                "背景简约而有氛围，整体色调柔和高级。"
            ),
            video_prompt=(
                "2D 韩漫动态：轻量动画化处理，人物主要动作为局部运动与微表情；"
                "镜头以推拉、平移与特写切换为主；线条稳定不抖动，"
                "渐变上色保持柔和，避免生硬变形。"
            ),
        ),
        StylePromptSet(
            key="otome-2d",
            label="2D乙女",
            image_prompt=(
                "2D 乙女向风格：唯美华丽的日系插画，柔美轮廓与精致五官；"
                "发丝与服饰细节繁复，蕾丝、珠宝等装饰精美；色彩粉嫩柔和，"
                "大量柔光与花瓣、星光点缀，整体浪漫梦幻。"
            ),
            video_prompt=(
                "乙女向梦幻动态：轻柔缓慢的运镜，人物动作优雅柔和；"
                "花瓣飘落、星光闪烁等氛围粒子细腻；发丝与裙摆轻微摆动；"
                "画面保持唯美柔光，过渡平滑梦幻。"
            ),
        ),
        StylePromptSet(
            key="chinese-animation-2d",
            label="2D国漫",
            image_prompt=(
                "2D 国漫风格：融合东方美学的二维动画，线条刚柔并济；"
                "人物造型东方化，服饰纹样考究；上色层次丰富，水墨晕染与平涂结合；"
                "场景含中式建筑与自然山水，色彩典雅。"
            ),
            video_prompt=(
                "2D 国漫运动：动作设计带有东方武术韵律，节奏明快；"
                "镜头调度大气，常见大景别切换；水墨与粒子特效点缀得当；"
                "线条风格统一，保持国漫独特气质。"
            ),
        ),
        StylePromptSet(
            key="cg",
            label="CG风格",
            image_prompt=(
                "高品质 CG 渲染：全局光照与高精度模型，材质细节丰富（金属、玻璃、布料质感真实）；"
                "景深与体积光自然；色彩经过专业调色，画面干净通透；"
                "兼具真实感与艺术加工，细节锐利。"
            ),
            video_prompt=(
                "CG 渲染动态：流畅的 3D 运动与相机运镜，运动模糊自然；"
                "布料、毛发解算细腻；光影与反射随镜头连续；渲染品质稳定，无闪烁与噪点。"
            ),
        ),
        StylePromptSet(
            key="cartoon-3d",
            label="3D卡通",
            image_prompt=(
                "3D 卡通风格：圆润夸张的角色造型，大眼睛与简洁面部结构；"
                "色彩明快高饱和，材质干净柔和（类似黏土或玩具质感）；"
                "场景道具造型Q弹，轮廓清晰，整体童趣可爱。"
            ),
            video_prompt=(
                "3D 卡通动态：夸张但自然的挤压与拉伸动画，动作弹性十足；"
                "镜头活泼，快节奏切换与趣味构图；角色表情丰富夸张；"
                "色彩明亮统一，保持卡通片质感。"
            ),
        ),
        StylePromptSet(
            key="cyberpunk-cg",
            label="CG赛博朋克",
            image_prompt=(
                "赛博朋克 CG 风格：未来都市霓虹夜景，全息投影与巨型广告牌；"
                "湿润街道反射五彩霓虹；人物融入机械义体与科技服装细节；"
                "高对比光影，青紫与洋红主色调，画面充满科技压迫感。"
            ),
            video_prompt=(
                "赛博朋克动态：霓虹闪烁与全息影像流动，雨幕与蒸汽持续运动；"
                "运镜多低角度滑动与穿梭镜头，速度感强；机械义体动作利落；"
                "霓虹光晕稳定，保持高对比冷色调。"
            ),
        ),
        StylePromptSet(
            key="gongbi",
            label="工笔画",
            image_prompt=(
                "中国传统工笔画风格：精细白描勾线与层层晕染的设色；"
                "绢本/宣纸质感，矿物颜料色彩沉稳（石青、石绿、朱砂、赭石）；"
                "花鸟人物造型典雅，线条工整匀净，装饰性强，留白构图讲究。"
            ),
            video_prompt=(
                "工笔画动态：以二维平移、推拉运镜为主，画面如徐徐展开的画卷；"
                "笔触与晕染质感保持静止统一，仅局部元素（流水、烟雾、花瓣）"
                "做轻微动态；色彩沉稳不跳变，保持古画韵味。"
            ),
        ),
    )
}

STYLE_KEYS: tuple[str, ...] = tuple(STYLE_PROMPTS.keys())


def get_style(key: str | None) -> StylePromptSet | None:
    """按 key 取风格提示词集；未知 key 返回 None。"""
    if not key:
        return None
    return STYLE_PROMPTS.get(key)


def image_style_suffix(key: str | None) -> str:
    """生图风格定调段落；未知 key 返回空串（不注入）。"""
    style = get_style(key)
    if style is None:
        return ""
    return f"画面风格遵循「{style.label}」：{style.image_prompt}"


def video_style_suffix(key: str | None) -> str:
    """生视频风格定调段落；未知 key 返回空串（不注入）。"""
    style = get_style(key)
    if style is None:
        return ""
    return f"视频风格遵循「{style.label}」：{style.video_prompt}"


def image_project_style_suffix(
    key: str | None,
    custom_style_prompt: str | None,
) -> str:
    """渲染项目级生图风格；自定义风格由项目配置直接提供。"""
    custom = (custom_style_prompt or "").strip()
    if custom:
        return f"画面风格遵循项目自定义要求：{custom}"
    return image_style_suffix(key)


def video_project_style_suffix(
    key: str | None,
    custom_style_prompt: str | None,
) -> str:
    """渲染项目级生视频风格；与生图链路使用同一配置来源。"""
    custom = (custom_style_prompt or "").strip()
    if custom:
        return f"视频风格遵循项目自定义要求：{custom}"
    return video_style_suffix(key)


def list_styles() -> list[dict]:
    """风格清单（后端唯一事实来源）：[{key, label}]。"""
    return [{"key": style.key, "label": style.label} for style in STYLE_PROMPTS.values()]
