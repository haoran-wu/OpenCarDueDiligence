import type { InspectionStage } from "./types";

/**
 * Browser-safe projection of data/checklists/five_stage_inspection_v1.yaml.
 *
 * The IDs intentionally match the deterministic risk engine. Keep the source
 * YAML as the policy/provenance record and use the parity test before changing
 * either side. Labels are bilingual so a saved inspection remains readable
 * after the UI language is switched.
 */
export const CANONICAL_INSPECTION_STAGES = [
  {
    id: "before",
    title: "看车前 / Before the visit",
    items: [
      ["vin_received", "出发前取得完整 VIN。 / Obtain the full VIN before traveling."],
      ["title_photo_redacted", "索要打码后的 title 照片，保留 VIN、州、title 状态和 lien 栏。 / Request a redacted title photo showing VIN, state, title status, and lien area."],
      ["seller_identity_match_plan", "确认卖家现场出示证件核对姓名；云端不保存原始姓名。 / Confirm the seller will show ID for an in-person name match; do not store the raw name in cloud data."],
      ["cold_start_requested", "要求卖家到达前不要启动或热车。 / Ask the seller not to start or warm the vehicle before arrival."],
      ["ppi_permission", "取得独立 PPI 和道路试驾许可。 / Obtain permission for an independent pre-purchase inspection and road test."],
      ["service_records", "索要保养发票、验车拒绝单、召回完成记录及全部钥匙。 / Request maintenance invoices, inspection rejection notices, recall completion records, and both keys."],
      ["recall_lookup", "用 VIN 在 NHTSA 和厂家查询未完成召回；车型级数据不能证明该车已完成召回。 / Check open recalls by VIN with NHTSA and the manufacturer; model-level recall data cannot prove completion."],
    ],
  },
  {
    id: "exterior",
    title: "外观与结构 / Exterior and structure",
    items: [
      ["vin_all_locations", "核对仪表台、车门标签、title 和诊断扫描上的 VIN。 / Match VIN on dashboard, door label, title, and diagnostic scan."],
      ["panel_gaps", "在一致光线下比较钣金缝隙、螺丝、密封胶、漆面纹理和色差。 / Compare panel gaps, fasteners, seam sealer, paint texture, and color in consistent light."],
      ["overspray_welds", "检查漆雾、遮蔽线、焊点变化、金属褶皱或更换标签。 / Look for overspray, masking lines, disturbed welds, wrinkled metal, or replacement labels."],
      ["glass_lamps", "记录玻璃日期码、裂纹、崩点、灯内水汽及配备车型的自动调平。 / Record glass date codes, cracks, chips, lamp moisture, and lamp self-leveling where equipped."],
      ["tires", "记录轮胎 DOT 日期、尺寸一致性、各位置胎纹、胎壁损伤和偏磨。 / Record tire DOT dates, size match, tread depth across each tire, sidewall damage, and uneven wear."],
      ["rust", "检查副车架、顶车边、刹车/燃油管、悬挂固定点、门槛和底板锈蚀。 / Inspect subframes, pinch welds, brake/fuel lines, suspension mounts, rocker panels, and floor for corrosion."],
      ["flood_signs", "检查低位空腔、备胎槽、插头、座椅滑轨和地毯下方有无泥沙、异味或水线。 / Check low cavities, spare-tire well, connectors, seat rails, and under-carpet areas for silt, odor, or water marks."],
      ["fluid_ground", "检查地面及发动机、变速箱、车轴下部有无新鲜液体。 / Inspect the ground and lower engine/transmission/axle areas for fresh fluid."],
    ],
  },
  {
    id: "interior",
    title: "内饰与电气 / Interior and electrical",
    items: [
      ["warning_lamp_self_test", "通电时确认 MIL、ABS、SRS 等警告灯会亮起，启动后按正常逻辑熄灭。 / With ignition on, verify MIL, ABS, SRS, and other required warning lamps illuminate and then behave normally after start."],
      ["module_coverage", "记录实际扫描了哪些模块；未扫描的 ABS/SRS/车身模块保持 UNKNOWN。 / Record which modules were actually scanned; unscanned ABS/SRS/body modules remain UNKNOWN."],
      ["moisture", "检查地毯、顶棚、立柱、备胎槽和空调滤芯区域是否潮湿或发霉。 / Check carpets, headliner, pillars, spare-tire well, and cabin filter area for moisture or mold."],
      ["hvac", "测试暖风、冷气、各档风量、出风方向、内循环和除霜。 / Test heat, cold A/C, blower speeds, vent direction, recirculation, and defrost."],
      ["switches", "测试车窗、门锁、后视镜、喇叭、雨刷/喷水、灯光、电源、摄像头和车机。 / Test windows, locks, mirrors, horn, wipers, washers, lights, outlets, camera, and infotainment."],
      ["roof", "让天窗或敞篷完整运行一轮，并检查排水、密封和警告信息。 / Operate sunroof or convertible roof through a full cycle and inspect drains, seals, and warning messages."],
      ["restraints", "检查安全带、卡扣、座椅、头枕和可见气囊盖是否损坏或被动过。 / Inspect seat belts, buckles, seats, head restraints, and visible airbag covers for damage or tampering."],
      ["keys", "测试全部钥匙、遥控、芯片防盗和机械应急钥匙。 / Test every supplied key, remote, immobilizer, and emergency blade."],
    ],
  },
  {
    id: "drive",
    title: "冷启动与试驾 / Cold start and road test",
    items: [
      ["cold_verified", "启动前用冷却液温度/实时数据或谨慎触摸确认发动机为冷车。 / Verify the engine is cold using coolant temperature/live data or careful touch before start."],
      ["start_quality", "观察启动时间、怠速稳定性、烟雾、燃油味、警告灯和异常机械声。 / Observe crank time, idle stability, smoke, fuel smell, warning lights, and abnormal mechanical noise."],
      ["fluids_temperature", "观察水温和警告；若过热、机油压力报警或大量漏液立即停止。 / Watch coolant temperature and warning messages; stop for overheating, oil-pressure warning, or major fluid loss."],
      ["transmission", "冷车和热车测试前进/倒挡结合与换挡，记录转速飘升、打滑、抖动、延迟、齿轮声或冲击。 / Test engagement and shifts cold and warm, including reverse; record flare, slip, shudder, delay, grinding, or harsh engagement."],
      ["clutch", "手动挡检查离合结合点、负载打滑、抖动、踏板、同步器和分离轴承噪音。 / For a manual, assess clutch take-up, slip under load, chatter, pedal feel, synchronizers, and release-bearing noise."],
      ["brakes", "测试直线渐进制动和驻车制动，记录抖动、跑偏、异响、助力不足或警告灯。 / Test straight, progressive braking and parking brake; record pulsation, pull, noise, weak assist, or warning lamps."],
      ["steering_suspension", "在不同路面检查方向回正、助力、间隙、轴承嗡鸣、底盘撞击、弹跳和振动。 / Check steering centering, assist, play, wheel-bearing hum, clunks, bounce, and vibration over varied surfaces."],
      ["highway_load", "在安全合法条件下测试持续车速和中等负载下的增压、冷却、失火、振动和换挡。 / Where safe and legal, test sustained speed and moderate load for boost, cooling, misfire, vibration, and transmission behavior."],
      ["post_drive_scan", "试驾后再次读取 stored、pending、permanent codes 和 readiness，绝不清码。 / Re-scan stored, pending, and permanent codes and readiness after the road test without clearing anything."],
    ],
  },
  {
    id: "ppi",
    title: "举升检查 / 专业 PPI / Lift inspection / professional PPI",
    items: [
      ["structural_underbody", "举升检查纵梁、副车架、固定点、底板、拉伸/焊修痕迹和锈蚀。 / Inspect rails, subframes, mounting points, floor, prior pulls/welds, and corrosion on a lift."],
      ["leaks", "确认机油、变速箱油、冷却液、燃油、刹车油和差速器渗漏的来源及程度。 / Identify source and severity of engine oil, transmission fluid, coolant, fuel, brake fluid, and differential leaks."],
      ["brake_measurements", "测量刹车片/盘，检查软管和硬管、卡钳活动及刹车油状态。 / Measure pad/rotor condition, inspect hoses and hard lines, verify caliper movement and fluid condition."],
      ["steering_suspension_lift", "检查球头、拉杆、控制臂胶套、减震器、轮毂轴承、CV 万向节和防尘套。 / Check ball joints, tie rods, control-arm bushings, struts/shocks, wheel bearings, CV joints, and boots."],
      ["exhaust_emissions", "检查排气泄漏、催化器损坏/改动、氧传感器线路和排放设备。 / Inspect exhaust leaks, catalyst damage/tampering, oxygen-sensor wiring, and emissions equipment."],
      ["cooling_pressure", "当车龄、车型风险、残留物、气味或历史提示时，对冷却系统做压力测试。 / Pressure-test the cooling system when age, model risk, residue, odor, or history warrants it."],
      ["compression_leakdown", "当失火、冒烟、异响或车型风险提示时，做缸压/泄漏或相对压缩测试。 / Perform compression/leak-down or relative-compression testing when misfire, smoke, noise, or model risk warrants it."],
      ["hybrid_ev_battery", "混动/纯电车使用合适设备检查电池健康、模块/单体均衡、绝缘、热管理和充电系统。 / For hybrid/EV vehicles, obtain battery health, module/cell balance, isolation, thermal, and charging-system results with appropriate equipment."],
      ["full_module_scan", "用合适设备扫描动力、ABS、SRS、车身、变速箱、混动/EV 和厂家模块，并保存报告。 / Use a capable scan tool for powertrain, ABS, SRS, body, transmission, hybrid/EV, and manufacturer modules; preserve the report."],
    ],
  },
] as const satisfies ReadonlyArray<{
  id: InspectionStage["id"];
  title: string;
  items: ReadonlyArray<readonly [string, string]>;
}>;

export const CANONICAL_INSPECTION_ITEM_COUNT = CANONICAL_INSPECTION_STAGES.reduce(
  (total, stage) => total + stage.items.length,
  0,
);

export function createInspectionTemplate(): InspectionStage[] {
  return CANONICAL_INSPECTION_STAGES.map((stage) => ({
    id: stage.id,
    title: stage.title,
    checks: stage.items.map(([id, label]) => ({ id, label, status: "unknown" })),
  }));
}
