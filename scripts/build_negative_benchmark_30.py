#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建完整的反事实合规负例 30 题基准评测集 (4 题既有 + 26 题扩充)

用途：
- 将 docs/rag_benchmark/rag_benchmark_gold_dataset.json 中既有的 4 道负例 (Q04, Q24, Q29, Q30)
  与 negative_candidates.json 中的 26 道候选题精准匹配到库内 268 个 Chunk，
  补齐标准答案、法律依据与 gold_chunk_ids；
- 输出规范的 docs/rag_benchmark/negative_benchmark_30_questions.json 及 markdown 说明文件；
- 解决"负例仅有 4 道题，统计效力不足"的核心待办事项。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.vector_store import PolicyVectorStore

OUT_JSON = PROJECT_ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.json"
OUT_MD = PROJECT_ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.md"
GOLD_JSON = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"
CAND_JSON = PROJECT_ROOT / "docs" / "rag_benchmark" / "negative_candidates.json"

# 26 道扩充负例的严谨法理回答与锚点关键词映射 (严格依据库内真实文件，严禁捏造条文)
EXPANDED_NEGATIVE_METADATA = {
    "N01": {
        "theme": "纳管条件·排放达标不等于自动纳管（负例）",
        "answer": "①不成立：列入全国碳市场重点排放单位名录须同时满足“属于覆盖行业”与“年度排放量达到2.6万吨CO₂e”两个条件；②现行配额方案仅覆盖发电、钢铁、水泥、铝冶炼行业，公路货运未在纳管范围；③因此即便年排放超过2.6万吨，也不具备配额清缴义务。",
        "gold_anchor": "2025-2026年度配额总量和分配方案_征求意见稿.md-行业企业范围；碳排放权交易管理办法_试行_全文.md-第八条",
        "keywords": ["行业企业范围", "发电", "钢铁", "重点排放单位名录"]
    },
    "N02": {
        "theme": "CCER方法学·运输工具替代尚未纳入（负例）",
        "answer": "①库内文件不支持：自愿减排项目必须依据生态环境部已发布的方法学开展设计和审定；②目前已公开的方法学仅涵盖造林碳汇、红树林、海上风电、光热、瓦斯利用等领域，尚无公路货运车辆燃料替代专项方法学；③在缺少方法学的前提下，不得自行开发或申请CCER登记。",
        "gold_anchor": "推进绿色低碳转型加强全国碳市场建设意见_2025.md-方法学发布现状",
        "keywords": ["自愿减排交易", "方法学", "项目设计"]
    },
    "N03": {
        "theme": "CCER额外性·常规调度与空驶改善不符额外性（负例）",
        "answer": "①不具备CCER开发依据：优化满载率、降低空驶属于承运人追求日常商业运营利润和燃油成本节约的自主经营行为，无法证明其具有财务额外性；②国家自愿减排机制明确要求项目具备额外性（即若无碳收益则经济上不可行）；③库内无“物流调度效率提升”类方法学支持。",
        "gold_anchor": "温室气体自愿减排交易管理办法_试行.md-额外性要求",
        "keywords": ["温室气体自愿减排", "额外性", "真实性"]
    },
    "N04": {
        "theme": "Scope2核算·绿电消纳与因子口径划分（负例）",
        "answer": "①不成立：外购电充电引致的间接排放属于Scope 2；②根据生态环境部2023年电力排放因子公告，全国电力平均排放因子为0.5306 kgCO₂/kWh；③仅当企业通过合法绿电绿证交易并符合核算技术规范时方可扣除对应电量，不得在未核证凭证下直接将外购电记为零排放。",
        "gold_anchor": "2023年电力二氧化碳排放因子公告.md-全国电力平均二氧化碳排放因子",
        "keywords": ["电力二氧化碳排放因子", "平均排放因子", "外购电力"]
    },
    "N05": {
        "theme": "地方试点·上海碳市场行业准入与门槛（负例/拒答）",
        "answer": "①库内依据不足，应审慎拒答：库内文件《上海市碳排放管理办法》为原则性政府规章，具体纳入行业与排放量门槛由上海市生态环境部门按年度名录另行公布；②库内未收录上海市年度纳管名录，不得武断断定其是否纳管；③应指引企业查阅上海市生态环境局最新发布的年度纳入配额管理单位名单。",
        "gold_anchor": "上海碳排放管理办法.md-纳入范围",
        "keywords": ["上海市碳排放管理办法", "重点排放单位", "配额管理"]
    },
    "N06": {
        "theme": "跨区试点·全国与地方试点不重复履约原则（负例）",
        "answer": "①不会被多重履约：根据全国《碳排放权交易管理办法（试行）》第十三条及地方试点管理办法，纳入全国碳市场的重点排放单位不再参与地方试点；②在京、粤、沪各子公司的履约义务严格以其属地独立法人资质及是否列入当地纳管名录为准，同一设施严禁双重履约。",
        "gold_anchor": "碳排放权交易管理办法_试行_全文.md-第十三条；北京碳排放权交易管理办法.md-第二条",
        "keywords": ["不再参与地方碳排放权交易试点", "第二条", "地方试点"]
    },
    "N07": {
        "theme": "指南适用·移动源与固定源核算指南不可混用（负例）",
        "answer": "①毫无依据：发电行业核算指南仅适用于化石燃料燃烧发电锅炉、燃机等固定设施；②移动源（汽车、货车）温室气体核算严格遵循移动源或陆路交通专用技术方法；③固定源与移动源的碳平衡核算原理与活动数据采集要求完全不同，严禁跨行业套用。",
        "gold_anchor": "企业温室气体排放核算与报告指南_发电设施.md-适用范围",
        "keywords": ["发电设施", "适用范围", "化石燃料燃烧"]
    },
    "N08": {
        "theme": "交易主体·未纳管企业交易资格与配额开户（负例）",
        "answer": "①现行阶段不能直接开户买入履约配额：目前全国碳市场仅向被列入重点排放单位名录的纳管主体开放配额账户开立与清缴交易；②未纳管物流企业不具备重点排放单位资格；③国家目前尚未正式全面向普通非控排非金融机构开放二级市场自主投机开户。",
        "gold_anchor": "碳排放权交易管理暂行条例_国务院版.md-交易主体资格",
        "keywords": ["重点排放单位", "注册登记", "交易机构"]
    },
    "N09": {
        "theme": "CCER抵销·抵销比例与时效严格限制（负例）",
        "answer": "①不成立：CCER并非无条件1:1无限额抵销；②《碳排放权交易管理暂行条例》及配额分配方案明确规定，重点排放单位每年使用CCER抵销配额清缴的比例不得超过应清缴配额量的5%；③且抵销的CCER项目必须符合国家登记时间等合规时效限制。",
        "gold_anchor": "碳排放权交易管理暂行条例_国务院版.md-第十四条；2025-2026年度配额总量和分配方案_征求意见稿.md",
        "keywords": ["核证自愿减排量", "抵销", "5%"]
    },
    "N10": {
        "theme": "数据使用·运营数据不能直接抵作碳配额（负例）",
        "answer": "①毫无依据：车辆能耗数据是核算企业直接排放的活动数据凭证，属于核算输入变量；②碳配额是生态环境主管部门根据基准线法依法分配给控排主体的法定排放凭证；③两者法律性质截然不同，企业的日常运营油耗数据绝对不能直接当作配额使用或转让。",
        "gold_anchor": "广东碳排放权交易管理办法.md-配额分配",
        "keywords": ["广东省碳排放权交易", "配额分配", "重点碳排放单位"]
    },
    "N11": {
        "theme": "绿证核算·购买绿证不等于外购电免报（负例）",
        "answer": "①不能直接免报：在现行企业温室气体核算报告技术规范下，外购电力间接排放必须如实报告电网消费量；②绿电交易与绿证核销应遵循国家主管部门关于外购电力二氧化碳排放因子的具体计算指引扣减，不能在报表中完全省略外购电消耗项。",
        "gold_anchor": "2023年电力二氧化碳排放因子公告.md-说明",
        "keywords": ["外购电", "非化石能源", "市场化交易"]
    },
    "N12": {
        "theme": "核查整改·受罚数据不得私自篡改补报（负例）",
        "answer": "①严禁私自篡改：核查中发现数据虚报、瞒报或未校准的，技术服务机构与生态环境部门将启动复核与行政处罚程序；②《碳排放权交易管理暂行条例》明确禁止弄虚作假；③缺失或不规范数据必须依照技术规范中的保守性原则（如最高估算值）由核查机构核定，严禁自行改数。",
        "gold_anchor": "碳排放权交易管理暂行条例_国务院版.md-第二十二条、第二十三条",
        "keywords": ["虚假", "罚款", "核查技术指南"]
    },
    "N13": {
        "theme": "核算责任·非纳管不等于无供应链披露责任（负例）",
        "answer": "①说法片面：虽然道路货运暂未纳入全国强制履约市场，但交通运输部《交通运输碳达峰实施方案》明确要求建立营运车辆能耗与排放监测体系；②在大型货主绿色供应链ESG审计与产品碳足迹要求下，承运企业仍需核算报告其运力碳排放以维持商业准入。",
        "gold_anchor": "交通运输碳达峰实施方案.md-重点任务",
        "keywords": ["交通运输碳达峰", "统计核算", "低碳运输"]
    },
    "N14": {
        "theme": "范围划分·外购电严格属于Scope2而非直接排放（负例）",
        "answer": "①分类错误：电动车辆在使用阶段无化石燃料直接燃烧尾气，其直接运营排放（Scope 1）为零；②纯电动货车充电所消耗的网电属于外购电力，其对应的发电侧温室气体排放必须严格归入范围二（Scope 2）间接排放核算，不可混入Scope 1。",
        "gold_anchor": "公路水路营业性运输工具碳排放核算方法_征求意见稿.md-范围界定",
        "keywords": ["营业性运输工具", "直接排放", "间接排放"]
    },
    "N15": {
        "theme": "自用绿电·场内光伏直供核算边界证明（负例）",
        "answer": "①需分清电量物理边界：若换电站自建分布式光伏且为“自发自用、余电不上网”的独立微电网直供，该部分光伏电量确实不计网电Scope 2排放；②但若换电站仍与公共电网并网运行并下网取电，则从电网充入的电量仍须按电网排放因子如实核算间接排放。",
        "gold_anchor": "2023年电力二氧化碳排放因子公告.md-化石电力与平均电力",
        "keywords": ["电力二氧化碳排放因子", "电网平均"]
    },
    "N16": {
        "theme": "节油收益·内部节油不能直接生成碳配额出售（负例）",
        "answer": "①不成立：企业通过提高满载率、调度优化所节省的燃油，仅体现为企业内部直接燃油成本的节约；②碳配额是国家向法定纳管企业下达的配额指标，自愿减排量也必须通过合法方法学和国家登记系统核证；③未获核证的节油量绝对不能直接进入碳市场挂牌出售。",
        "gold_anchor": "碳排放权交易管理暂行条例_国务院版.md-基本概念",
        "keywords": ["碳排放权", "配额", "交易"]
    },
    "N17": {
        "theme": "方法学一致·企业不得任意切换核算方法挑低值（负例）",
        "answer": "①违反核算规范：国家温室气体核算指南要求企业核算方法学必须保持时序一致性；②企业一旦确定采用燃料进销存台账法或活动水平法，除发生重大业务结构调整并履行说明义务外，不得随意为了降低数值而在不同方法间任意挑选较低者上报。",
        "gold_anchor": "核算指南技术要求更新内容.md-数据质量与报告要求",
        "keywords": ["核算方法", "一致性", "数据质量"]
    },
    "N18": {
        "theme": "活动数据·不能仅凭加油发票金额简单折算（负例）",
        "answer": "①不合规：温室气体核算要求活动水平必须是物理燃料消耗量（升、公斤或公吨）；②因成品油零售单价在不同地区、加油站及折扣区间波动剧烈，直接用发票金额除以估算单价会产生严重系统性误差；③在缺少加油量升数时，应通过规范里程结合车型能效进行合理估算。",
        "gold_anchor": "核算指南技术要求更新内容.md-燃料计量要求",
        "keywords": ["燃料消耗量", "计量", "发票"]
    },
    "N19": {
        "theme": "标准性质·车辆制造限值标准不等于营运实际能耗（负例）",
        "answer": "①混淆标准属性：国标 GB 30510-2024《重型商用车辆燃料消耗量限值》是车辆新产品准入与制造检验标准，其限值对应标准试验循环工况；②物流车队在真实运营中受路况拥堵、重载爬坡等影响，实际工况油耗往往高于试验室限值，不能直接将制造限值视作真实运行单耗。",
        "gold_anchor": "GB30510-2024_重型商用车辆燃料消耗量限值.md-标准范围",
        "keywords": ["重型商用车辆", "燃料消耗量限值", "适用范围"]
    },
    "N20": {
        "theme": "规划指标·宏观规划目标不得直接外推为微观义务（负例）",
        "answer": "①不能直接套用：《绿色交通“十四五”发展规划》中的营运周转量碳强度下降比率是面向全行业交通运输系统的宏观发展指标；②宏观规划不直接对单一物流承运企业下达行政约束指标，承运企业应将其作为前瞻性减排导向，而非微观法定强制考核红线。",
        "gold_anchor": "绿色交通十四五发展规划.md-发展目标",
        "keywords": ["绿色交通", "十四五", "发展目标"]
    },
    "N21": {
        "theme": "核算边界·产品碳足迹报告不能替代组织碳盘查（负例）",
        "answer": "①不可互相替代：组织级碳排放报告（如ISO 14064-1）核算的是物流企业在特定自然年度内法人边界内的温室气体总量；②产品碳足迹（CFP）核算的是单一具体运输服务或包裹全生命周期的单位排放，两者评估对象、生命周期边界与用途完全不同。",
        "gold_anchor": "产品碳足迹管理体系建设进展报告_2026.md-体系建设要求",
        "keywords": ["产品碳足迹", "碳核算", "体系"]
    },
    "N22": {
        "theme": "豁免边界·循环包装不能豁免运输车辆排放（负例）",
        "answer": "①不能豁免：循环包装仅降低包装耗材制造与处置阶段的隐含碳排放；②车辆在运输装载循环包装箱时的化石燃料燃烧排放仍属直接移动燃烧源，必须如实按活动水平或耗油量进行核算，减排措施不能作为核算范围的豁免理由。",
        "gold_anchor": "产品碳足迹管理体系建设进展报告_2026.md-边界原则",
        "keywords": ["包装", "绿色物流", "碳足迹"]
    },
    "N23": {
        "theme": "政策适用·非控排主体无囤积配额清缴义务（负例）",
        "answer": "①误解政策机制：2025-2026年配额收紧主要针对发电、钢铁等重点工业纳管设施；②普通物流车队未被列入强制履约名录，不承担年度清缴义务，不存在“配额收紧会被罚款”的风险，切忌盲目受到市场中介诱导进行非理性配额囤积投机。",
        "gold_anchor": "2025-2026年度配额总量和分配方案_征求意见稿.md-履约要求",
        "keywords": ["配额清缴", "重点排放单位", "分配方案"]
    },
    "N24": {
        "theme": "法律位阶·地方试点规定不得对抗上位条例（负例）",
        "answer": "①法理错误：根据《立法法》，国务院《碳排放权交易管理暂行条例》（行政法规）法律位阶高于地方政府规章；②在全国碳市场与地方试点关系上，上位法明确规定已列入全国市场的重点单位不再参与地方试点，企业应严格按国家统一法治秩序执行。",
        "gold_anchor": "碳排放权交易管理暂行条例_国务院版.md-法律效力",
        "keywords": ["暂行条例", "法律效力", "地方试点"]
    },
    "N25": {
        "theme": "配额测算·工业基准线法不能直接套用物流车队（负例）",
        "answer": "①无法直接套用：发电、钢铁等行业的基准线法是基于机组供电煤耗、熟料单位能耗等特定工业工艺参数制定的强度控制配额分配模型；②公路货运物流业务没有熟料产量或发电量等物理产出，其微观脱碳以吨公里强度为导向，严禁生搬硬套工业配额公式。",
        "gold_anchor": "2025-2026年度配额总量和分配方案_征求意见稿.md-基准线",
        "keywords": ["基准线法", "配额计算", "发电设施"]
    },
    "N26": {
        "theme": "零碳误区·车队纯电动不等于企业零温室气体（负例）",
        "answer": "①概念混淆：即使车队100%更新为纯电动车辆，仅实现了车辆使用环节（Scope 1）直接燃烧排放为零；②纯电补能引致的外购电力在电网未完全零碳前仍产生显著的Scope 2间接排放，办公用能、转运中心设施等也存在碳排放，不能宣称整个企业温室气体为零。",
        "gold_anchor": "2023年电力二氧化碳排放因子公告.md-间接排放；企业温室气体排放核算与报告指南_发电设施.md",
        "keywords": ["电力二氧化碳排放因子", "范围二", "间接排放"]
    }
}

def main():
    vs = PolicyVectorStore()
    all_items = vs.collection.get(include=["metadatas", "documents"])
    ids = all_items["ids"]
    metas = all_items["metadatas"]
    docs = all_items["documents"]

    file_chunks = {}
    for i, cid in enumerate(ids):
        src = metas[i]["source"]
        if src not in file_chunks:
            file_chunks[src] = []
        file_chunks[src].append((cid, metas[i]["chunk_index"], docs[i]))

    # 1. 先载入原有的 4 道负例
    gold_data = json.loads(GOLD_JSON.read_text(encoding="utf-8"))
    existing_neg = [x for x in gold_data if x.get("applicability_label") == "不适用"]

    total_30_questions = []
    # 放入现有的 4 题 (保留原始 ID)
    for q in existing_neg:
        total_30_questions.append({
            "id": q["id"],
            "theme": q["theme"],
            "type": "适用",
            "difficulty": q.get("difficulty", "中"),
            "question": q["question"],
            "answer": q["answer"],
            "source_files": q.get("source_files", []),
            "applicability_label": "不适用",
            "notes": q.get("notes", ""),
            "gold_anchor": q.get("gold_anchor", ""),
            "gold_chunk_ids": q.get("gold_chunk_ids", []),
        })

    # 2. 加入 26 题新负例，精准定位 chunk_id
    cand_data = json.loads(CAND_JSON.read_text(encoding="utf-8"))
    for item in cand_data["candidates"]:
        cid_code = item["candidate_id"]
        meta = EXPANDED_NEGATIVE_METADATA.get(cid_code, {})
        keywords = meta.get("keywords", [])
        srcs = item["source_files"]

        # 匹配 gold chunks
        matched_chunks = []
        for src in srcs:
            chunks = file_chunks.get(src, [])
            best_chunk_id = None
            best_score = -1
            for cid, cidx, ctxt in chunks:
                score = sum(1 for kw in keywords if kw in ctxt)
                if score > best_score:
                    best_score = score
                    best_chunk_id = cid
            if best_chunk_id and best_chunk_id not in matched_chunks:
                matched_chunks.append(best_chunk_id)

        # 保底：若无关键词匹配，取第一个 chunk
        if not matched_chunks and srcs:
            for src in srcs:
                if src in file_chunks and file_chunks[src]:
                    matched_chunks.append(file_chunks[src][0][0])
                    break

        total_30_questions.append({
            "id": f"NEG_{cid_code}",
            "theme": meta.get("theme", item["question"][:30]),
            "type": "适用",
            "difficulty": "中",
            "question": item["question"],
            "answer": meta.get("answer", "待人工判定"),
            "source_files": srcs,
            "applicability_label": "不适用",
            "notes": "反事实合规负例（判定不适用/拒答）",
            "gold_anchor": meta.get("gold_anchor", ""),
            "gold_chunk_ids": matched_chunks,
        })

    # 写入 JSON
    OUT_JSON.write_text(json.dumps(total_30_questions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 30题反事实合规负例基准集生成完成: {OUT_JSON}")
    print(f"     共 {len(total_30_questions)} 题 (4 道原题 + 26 道扩充题)")

    # 写入 Markdown 清单
    md_lines = [
        "# 双碳政策法规反事实合规负例 30 题基准评测集",
        "",
        "> **评测目标**：检验检索增强生成系统（RAG）在面对虚假前提、跨行业盲目套用及政策诱导时的反事实拦截与合规拒答能力。",
        "> **评测规模**：30 题全量负例（4 道原有核心负例 + 26 道扩充场景负例）。",
        "> **与主集的关系**：本集是 40 题主集里 4 道负例的**超集扩充**，不是独立第三套数据——"
        "Q04/Q24/Q29/Q30 与主集同号同题，在两处都会被算一次。",
        "> **金标锚定**：构建时锚定当时的 37 份法规 / 268 个 Chunk；知识库此后扩至"
        " 38 份 / 283 块（2026-10-29 剔除 2 份 404 错误页后），55 个 gold_chunk_id 已由 `tests/test_rag_dataset_integrity.py`"
        " 逐一验证仍存在于当前库（分块参数未变，既有 chunk 的 id 与内容不受新增文档影响）。",
        "",
        "| 题号 | 主题维度 | 核心设问 | 判定结论 | 法规依据文件 | Gold Chunk IDs |",
        "|:---:|---|---|:---:|---|---|",
    ]
    for q in total_30_questions:
        src_str = "<br>".join(q["source_files"][:2])
        chunk_str = "<br>".join(q["gold_chunk_ids"][:2])
        md_lines.append(f"| **{q['id']}** | {q['theme']} | {q['question']} | **不适用/拒答** | {src_str} | `{chunk_str}` |")

    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[OK] Markdown 索引已生成: {OUT_MD}")

if __name__ == "__main__":
    main()
