/**
 * dsh-plugin-carbon-asset: DeepSeek Harness 官方规范生态插件
 *
 * 严格对齐 DeepSeek Harness (@deepseek-ai/dsh-tools) 规范与 Post-mortem 0001 规范：
 * 1. 采用命名空间导出 (name, inject, apply)，严禁使用 export default (避免 Loader 丢弃 inject 导致崩溃)；
 * 2. 所有工具 parameters 经由 defineTool 编译为合规 JSON Schema 对象 (type: "object", properties, required)；
 * 3. 严格声明 output.schema 与 output.render，杜绝模型系统提示词构建与对话流断流。
 */
import { CarbonEngineBridge } from './bridge.js';
export const name = 'carbon-asset';
export const inject = ['tools'];
/**
 * 解析 dsh-tools 的 defineTool：优先取宿主注入的全局 dshDefineTool
 * 或同步 require；不在模块顶层 await（避免 CJS require(esm) 加载阻塞）。
 */
function resolveDefineTool() {
    try {
        const g = (typeof globalThis !== 'undefined' ? globalThis : {}) || {};
        if (typeof g.dshDefineTool === 'function') {
            return g.dshDefineTool;
        }
        const req = typeof g.require === 'function' ? g.require : null;
        if (req) {
            try {
                const dshTools = req('@deepseek-ai/dsh-tools');
                if (dshTools && typeof dshTools.defineTool === 'function') {
                    return dshTools.defineTool;
                }
            }
            catch {
                // 未安装，回退内置编译器
            }
        }
    }
    catch {
        // 任何异常都回退内置编译器
    }
    return null;
}
/**
 * 内置符合 dsh-tools 规范的 ToolDefinition 编译器
 */
function createToolDefinition(spec) {
    const dshDefineTool = resolveDefineTool();
    if (typeof dshDefineTool === 'function') {
        try {
            return dshDefineTool({
                name: spec.name,
                description: spec.description,
                parameters: spec.parameters,
                output: {
                    schema: { type: 'object', additionalProperties: true },
                    render: (_args, value) => [
                        { type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
                    ],
                },
                execute: spec.execute,
            });
        }
        catch {
            // 降级为自编译
        }
    }
    // 严格编译 ParameterSchemaSpec 为标准 JSON Schema 对象
    const properties = {};
    const required = [];
    for (const [key, prop] of Object.entries(spec.parameters)) {
        if (prop.required) {
            required.push(key);
        }
        const compiled = {
            type: prop.type,
        };
        if (prop.description) {
            compiled.description = prop.description;
        }
        if (prop.type === 'array' && prop.items) {
            const items = {
                type: prop.items.type,
                additionalProperties: prop.items.additionalProperties !== undefined ? prop.items.additionalProperties : true,
            };
            if (prop.items.description) {
                items.description = prop.items.description;
            }
            if (prop.items.properties) {
                const itemProps = {};
                const itemReq = [];
                for (const [pk, pv] of Object.entries(prop.items.properties)) {
                    const pval = pv;
                    if (pval.required)
                        itemReq.push(pk);
                    itemProps[pk] = {
                        type: pval.type,
                        ...(pval.description ? { description: pval.description } : {}),
                    };
                }
                items.properties = itemProps;
                if (itemReq.length > 0)
                    items.required = itemReq;
            }
            compiled.items = items;
        }
        else if (prop.type === 'object') {
            compiled.additionalProperties = prop.additionalProperties !== undefined ? prop.additionalProperties : true;
            if (prop.properties) {
                const objProps = {};
                const objReq = [];
                for (const [pk, pv] of Object.entries(prop.properties)) {
                    const pval = pv;
                    if (pval.required)
                        objReq.push(pk);
                    objProps[pk] = {
                        type: pval.type,
                        ...(pval.description ? { description: pval.description } : {}),
                    };
                }
                compiled.properties = objProps;
                if (objReq.length > 0)
                    compiled.required = objReq;
            }
        }
        properties[key] = compiled;
    }
    const parametersSchema = {
        type: 'object',
        properties,
        additionalProperties: false,
    };
    if (required.length > 0) {
        parametersSchema.required = required;
    }
    return {
        name: spec.name,
        description: spec.description,
        parameters: parametersSchema,
        output: {
            schema: { type: 'object', additionalProperties: true },
            render: (_args, value) => [
                { type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
            ],
        },
        execute: spec.execute,
    };
}
export function apply(ctx, config = {}) {
    const bridge = new CarbonEngineBridge(config);
    // 1. 车队碳排放基线测算工具
    ctx.tools?.register(createToolDefinition({
        name: 'carbon_calculate',
        description: '测算物流企业车队的年度直接运营碳排放总量 (tCO2e)、模拟碳预算对标差额及碳价情景合规成本。',
        parameters: {
            company_name: { type: 'string', required: true, description: '企业或车队名称' },
            fleet: {
                type: 'array',
                required: true,
                description: '车队分组列表，每组包含 vehicle_type(车型), count(车辆数), annual_km(年均公里数), load_factor(满载率 0~1)',
                items: {
                    type: 'object',
                    additionalProperties: true,
                    description: '车型分组信息',
                    properties: {
                        vehicle_type: { type: 'string', required: true, description: '车型名称（如：重型柴油货车、中型柴油货车、轻型柴油货车、微型汽油货车、新能源物流车）' },
                        count: { type: 'number', required: true, description: '车辆数量（辆）' },
                        annual_km: { type: 'number', required: true, description: '单车年均公里数（km）' },
                        load_factor: { type: 'number', description: '平均满载率（0~1之间，默认0.75）' },
                    },
                },
            },
            scenario_reduction_target: {
                type: 'number',
                description: '模拟碳预算的情景减排紧缩目标，默认 0.10 (即90%历史强度基准)',
            },
        },
        async execute(args) {
            return await bridge.execute('/api/calculate', 'calculate', args);
        },
    }));
    // 2. TCO 全生命周期拥有成本与投资回收期测算工具
    ctx.tools?.register(createToolDefinition({
        name: 'carbon_tco_evaluate',
        description: '测算燃油货车替换为纯电动商用车的全生命周期综合拥有成本(TCO)、初始增量投资(ΔCAPEX)、年运营节省(ΔOPEX)、静态投资回收期(年)以及单位吨碳减排边际成本(MAC)。',
        parameters: {
            vehicle_type: { type: 'string', required: true, description: '目标替换的燃油车型（如 重型柴油货车、中型柴油货车、轻型柴油货车、微型汽油货车）' },
            replace_count: { type: 'number', required: true, description: '拟替换为纯电车的车辆数量' },
            annual_km: { type: 'number', required: true, description: '单车年均运营里程 (km)' },
            annual_co2_reduction_t: { type: 'number', description: '该批车辆年碳减排量 (tCO2e)，若不提供可根据默认排放因子自动估算' },
            diesel_price_yuan_per_l: { type: 'number', description: '自定义柴油价格 (元/L，默认 7.50)' },
            electricity_price_yuan_per_kwh: { type: 'number', description: '自定义综合充电电价 (元/kWh，默认 0.80)' },
            ev_vehicle_price_wan: { type: 'number', description: '自定义新能源车单车购置价 (万元)' },
            lifespan_years: { type: 'number', description: '评估周期年限 (默认 5 年)' },
        },
        async execute(args) {
            return await bridge.execute('/api/tco/calculate', 'tco', args);
        },
    }));
    // 3. 车队减排情景模拟工具
    ctx.tools?.register(createToolDefinition({
        name: 'carbon_reduction_scenario',
        description: '为车队组合配置减排措施（如将部分燃油车替换为纯电动车、提高调度满载率），评估减排潜力、对标成本节省及 TCO 投资回收期。',
        parameters: {
            baseline_fleet: {
                type: 'array',
                required: true,
                description: '基线车队配置列表',
                items: {
                    type: 'object',
                    additionalProperties: true,
                    description: '车型分组信息',
                    properties: {
                        vehicle_type: { type: 'string', required: true, description: '车型名称' },
                        count: { type: 'number', required: true, description: '车辆数量' },
                        annual_km: { type: 'number', required: true, description: '年均公里数' },
                        load_factor: { type: 'number', description: '满载率' },
                    },
                },
            },
            changes: {
                type: 'object',
                required: true,
                additionalProperties: true,
                description: '减排措施映射字典，如 {"替换为新能源物流车": 10, "提升满载率至0.85": 20}',
            },
            budget_reduction_target: {
                type: 'number',
                description: '基准预算缩减目标 (默认 0.10)',
            },
        },
        async execute(args) {
            return await bridge.execute('', 'reduction', args);
        },
    }));
    // 4. 碳市场政策法规智能问答工具
    ctx.tools?.register(createToolDefinition({
        name: 'carbon_policy_query',
        description: '基于中国碳排放权交易法规、CCER自愿减排机制与绿色交通双碳政策知识库，回答企业的政策合规、基准线与履约问题，带政策条款原文来源溯源。',
        parameters: {
            question: { type: 'string', required: true, description: '用户或企业的政策咨询问题' },
            carbon_profile: {
                type: 'object',
                additionalProperties: true,
                description: '可选的企业碳画像数据（如总排放量、车队规模、预算差额等）',
            },
        },
        async execute(args) {
            return await bridge.execute('/api/ask', 'policy', args);
        },
    }));
    // 5. 多企业/多车队碳资产横向对标工具
    ctx.tools?.register(createToolDefinition({
        name: 'carbon_enterprise_compare',
        description: '对 2 个及以上物流企业或车队进行横向碳对标比较，输出各企业排放排名、模拟碳预算差额排名及情景成本对比。',
        parameters: {
            companies: {
                type: 'array',
                required: true,
                description: '企业列表，每个企业包含 company_name 和 fleet 列表',
                items: {
                    type: 'object',
                    additionalProperties: true,
                    description: '单个企业车队信息',
                    properties: {
                        company_name: { type: 'string', required: true, description: '企业名称' },
                        fleet: {
                            type: 'array',
                            required: true,
                            description: '车队分组',
                            items: {
                                type: 'object',
                                additionalProperties: true,
                                properties: {
                                    vehicle_type: { type: 'string', required: true, description: '车型名称' },
                                    count: { type: 'number', required: true, description: '车辆数量' },
                                    annual_km: { type: 'number', required: true, description: '年均公里数' },
                                    load_factor: { type: 'number', description: '满载率' },
                                },
                            },
                        },
                        scenario_reduction_target: { type: 'number', description: '情景减排目标' },
                    },
                },
            },
        },
        async execute(args) {
            return await bridge.execute('/api/compare', 'compare', args);
        },
    }));
    // 6. 运输周转量与外购电间接排放综合对标工具
    ctx.tools?.register(createToolDefinition({
        name: 'carbon_turnover_evaluate',
        description: '核算物流车队实际货物周转量 (万吨公里) 及运输碳排放强度 (gCO2/t·km)，并测算纯电动车辆外购电引起的 Scope 2 间接排放量。',
        parameters: {
            fleet: {
                type: 'array',
                required: true,
                description: '车队分组列表',
                items: {
                    type: 'object',
                    additionalProperties: true,
                    properties: {
                        vehicle_type: { type: 'string', required: true, description: '车型名称' },
                        count: { type: 'number', required: true, description: '车辆数量' },
                        annual_km: { type: 'number', required: true, description: '单车年均公里数' },
                        load_factor: { type: 'number', description: '平均满载率 (0~1)' },
                    },
                },
            },
            region: {
                type: 'string',
                description: '所属省份或电网区域（如全国平均、广东、上海、北京等，用于匹配最新官方电网因子）',
            },
            green_electricity_ratio: {
                type: 'number',
                description: '绿电/绿证交易比例 (0.0~1.0，绿电部分折减外购电间接排放)',
            },
        },
        async execute(args) {
            return await bridge.execute('/api/turnover', 'turnover', args);
        },
    }));
}
