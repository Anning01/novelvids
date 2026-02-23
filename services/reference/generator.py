from openai import AsyncOpenAI

def build_sora_compatible_prompt(data):
    """
    为 Sora 2 优化的结构化提示词
    核心逻辑：使用身份锚点(Identity Anchors) + 空间多视角描述
    """
    asset_type = data.get("type")
    name = data.get("canonical_name")
    traits = data.get("base_traits")
    desc = data.get("description")

    # 通用电影级引导词：增强光影稳定性，降低 Sora 2 生成时的噪点
    cinema_prefix = "二次元风格，视频静帧画面，电影感构图，极高保真度，4K分辨率。"

    if asset_type == "person":
        # 针对 Sora 2 的人物一致性：生成三视图模式
        # 这种模式能让 Sora 学习到人物的全方位特征
        prompt = (f"{cinema_prefix}角色设计稿：{name}的全身三视图（正面、侧面、背面）。"
                  f"视觉特征锚点：{traits}。{desc}。"
                  "白色背景，平铺光，人体比例严谨，面部特征高度清晰且一致。")
    elif asset_type == "item":
        # 物品一致性：强调多角度细节和材质感
        prompt = (f"{cinema_prefix}{name}的多角度产品展示，具有{traits}的特征。{desc}。"
                  "摄影棚灯光，微距镜头，皮肤/材质纹理锐利，工作室渲染效果。")
    elif asset_type == "scene":
        # 场景一致性：强调空间深度，为 Sora 2 预留运镜空间
        prompt = (f"{cinema_prefix}{name}的宏大全景图，空间架构：{traits}。{desc}。"
                  "广角视角，丁达尔效应，细腻的光影层次，具有极强的空间立体感。")
    else:
        prompt = f"{cinema_prefix}{name}, {traits}, {desc}"

    return prompt


async def generate_for_sora_consistency(client: AsyncOpenAI, data, reference_images=None, model="doubao-seedream-4-5-251128"):
    """
    执行生成任务，支持多图参考 (异步)
    """
    final_prompt = build_sora_compatible_prompt(data)

    extra_body = {
        "sequential_image_generation": "disabled",
        "watermark": False
    }

    # 兼容 OpenAI 格式，将 image 参数放入 extra_body
    if reference_images:
        extra_body["image"] = reference_images

    try:
        response = await client.images.generate(
            model=model,
            prompt=final_prompt,
            size="2K",  # 建议 2K，若需更高精度可在控制台设为 4K
            response_format="url",
            n=1, # 显式指定只生成一张
            extra_body=extra_body
        )
        return response.data
    except Exception as e:
        print(f"生成异常: {e}")
        raise e
