import requests
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta  # ⬅️ 这里彻底修好了，把 timedelta 一并导入了
import os

# 解决 matplotlib 中文显示问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# ⚙️ 微信推送配置
# 1. 微信搜索公众号 "pushplus推送助手" 并关注
# 2. 点击公众号底部菜单 -> 发送信息 -> 复制你的 token
# 3. 粘贴到下面引号中
# ==========================================
PUSH_PLUS_TOKEN = "556cb7cf7bae48899847d62f6d774ce1" 


class CloudSeaAnalyzerPro:
    API_URL = "https://api.open-meteo.com/v1/ecmwf"
    PUSH_URL = "http://www.pushplus.plus/send"

    def __init__(self, target_locations):
        self.location_meta = {
            '潮安区坪坑头村': {
                'lat': 23.93803, 'lon': 116.67253, 'elev': 1072.0,
                'view_dir': '未提供，建议朝开阔山谷或日出方向'
            },
            '宋茶文化博物馆': {
                'lat': 23.93764, 'lon': 116.66578, 'elev': 1071.0,
                'view_dir': '未提供，建议朝开阔山谷或日出方向'
            },
            '望岭村民委员会': {
                'lat': 23.78964, 'lon': 116.65840, 'elev': 410.0,
                'view_dir': '海拔较低，大概率身处云下'
            },
            '双髻娘山': {
                'lat': 23.82095, 'lon': 116.73854, 'elev': 1005.0,
                'view_dir': '未提供，建议朝开阔山谷或日出方向'
            },
            '无水坳': {
                'lat': 23.76071, 'lon': 116.29202, 'elev': 939.0,
                'view_dir': '未提供，建议朝开阔山谷或日出方向'
            },
            '梅州鸿图嶂景区': {
                'lat': 23.77720, 'lon': 115.94539, 'elev': 1178.0,
                'view_dir': '梅州区域独立计算'
            },
            '鸳鸯寨': {
                'lat': 23.97898, 'lon': 116.36709, 'elev': 358.0,
                'view_dir': '海拔极低，大概率看平原雾气'
            },
            '潮安区崧顶茗宿东北': {
                'lat': 23.95482, 'lon': 116.65525, 'elev': 1106.0,
                'view_dir': '未提供，建议朝开阔山谷或日出方向'
            }
        }
        self.locations = target_locations

    def _fetch_weather_data(self, location):
        """获取 ECMWF 数据 + 每日日出日落时间"""
        meta = self.location_meta[location]
        params = {
            'latitude': meta['lat'],
            'longitude': meta['lon'],
            'hourly': ','.join([
                'temperature_2m', 'dew_point_2m', 'relative_humidity_2m',
                'wind_speed_10m', 'cloud_cover_low', 'cloud_cover_mid',
                'relative_humidity_850hPa'
            ]),
            'daily': 'sunrise,sunset',  # ⬅️ 获取每日日出日落
            'timezone': 'Asia/Shanghai',
            'forecast_days': 3,
            'wind_speed_unit': 'ms',
        }
        try:
            r = requests.get(self.API_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"[{location}] 数据获取失败: {e}")
            return None

    @staticmethod
    def _calc_lcl(temp_c, dew_c):
        return max(0.0, 125.0 * (temp_c - dew_c))

    def _get_wash_status(self, spot_elev, cloud_base):
        diff = spot_elev - cloud_base
        if diff >= 100:
            return f"🟢 安全观景 (人在云上 {diff:.0f}m)"
        elif -50 <= diff < 100:
            return f"🟡 擦边预警 (视线边缘 ±100m，可能时而清晰时而起雾)"
        else:
            return f"🔴 洗头警告 (人在雾中 {abs(diff):.0f}m)"

    def _score_hour(self, h, i, elev):
        t, td, rh = h['temperature_2m'][i], h['dew_point_2m'][i], h['relative_humidity_2m'][i]
        ws, low, mid = h['wind_speed_10m'][i], h['cloud_cover_low'][i], h['cloud_cover_mid'][i]
        rh850 = h['relative_humidity_850hPa'][i]

        lcl = self._calc_lcl(t, td)
        cloud_base = elev + lcl
        wash_status = self._get_wash_status(elev, cloud_base)

        score = 40 * (low / 100.0)
        if wash_status.startswith("🟢"): score += 30
        elif wash_status.startswith("🟡"): score += 15
        if ws < 3: score += 20
        elif ws < 5: score += 12
        elif ws < 8: score += 4
        if rh850 > 80: score += 10
        elif rh850 > 60: score += 5
        if mid > 70: score -= 15

        detail = {'temp': t, 'dew': td, 'rh': rh, 'ws': ws,
                  'low': low, 'mid': mid, 'cloud_base': cloud_base, 'wash_status': wash_status}
        return max(0, min(100, round(score))), cloud_base, detail

    def analyze(self):
        all_results = {}
        
        for loc in self.locations:
            data = self._fetch_weather_data(loc)
            if not data: continue
            
            h, d = data['hourly'], data['daily']
            meta = self.location_meta[loc]
            sunrise_times = [datetime.fromisoformat(t) for t in d['sunrise']]
            
            hourly = []
            for i, tstr in enumerate(h['time']):
                dt = datetime.fromisoformat(tstr)
                # 动态匹配：只要时间在当天日出前1小时到日出后3小时之间
                is_golden_time = False
                for sr in sunrise_times:
                    # ⬅️ 这里彻底修好了，直接使用 timedelta
                    if sr - timedelta(hours=1) <= dt <= sr + timedelta(hours=3):
                        is_golden_time = True
                        break
                
                if is_golden_time:
                    idx, cbase, detail = self._score_hour(h, i, meta['elev'])
                    hourly.append({'dt': dt, 'index': idx, 'cloud_base': cbase, **detail})

            best = max(hourly, key=lambda x: x['index']) if hourly else None
            ref_sunrise = sunrise_times[1].strftime('%H:%M') if len(sunrise_times) > 1 else 'N/A'
            all_results[loc] = {'hourly': hourly, 'best': best, 'meta': meta, 'sunrise': ref_sunrise}

            # ---------- 控制台打印 ----------
            print("=" * 60)
            print(f"【{loc}】(海拔 {meta['elev']}m | 明日日出: {ref_sunrise})")
            if best:
                print(f"  🕒 黄金时段最佳: {best['dt'].strftime('%m月%d日 %H:%M')}")
                print(f"  📊 云海指数: {best['index']} / 100")
                print(f"  🌫️ 云底海拔: {best['cloud_base']:.0f} m")
                print(f"  💇 状态: {best['wash_status']}")
            print("=" * 60)

        self._visualize(all_results)
        self._send_wechat_report(all_results)
        return all_results

    def _visualize(self, all_results):
        n = len(all_results)
        if n == 0: return
        fig, axes = plt.subplots(n, 1, figsize=(14, 4.5 * n))
        if n == 1: axes = [axes]
        
        for ax, (loc, res) in zip(axes, all_results.items()):
            hrs = res['hourly']
            if not hrs: continue
            labels = [x['dt'].strftime('%d日%H时') for x in hrs]
            idx = [x['index'] for x in hrs]
            colors = ['#2ca02c' if "🟢" in x['wash_status'] 
                      else '#ff7f0e' if "🟡" in x['wash_status'] 
                      else '#d62728' for x in hrs]
            
            ax.bar(range(len(hrs)), idx, color=colors, alpha=0.85)
            ax.set_xticks(range(len(hrs)))
            ax.set_xticklabels(labels, rotation=45, fontsize=8)
            ax.set_ylim(0, 100)
            ax.axhline(70, ls='--', color='gray', alpha=0.6)
            ax.set_title(f"{loc} (日出 {res['sunrise']}) | 绿=安全 橙=擦边 红=洗头")
            ax.grid(axis='y', ls='--', alpha=0.4)
        
        plt.tight_layout()
        plt.savefig('cloud_sea_chart.png', dpi=150)
        plt.show()
        print("\n✅ 图表已保存: cloud_sea_chart.png")

    def _send_wechat_report(self, all_results):
        """发送微信推送"""
        if PUSH_PLUS_TOKEN == "这里替换成你的 token":
            print("\n⚠️ 请先在代码顶部填入你的 pushplus token 才能启用微信推送！")
            return

        msg = "### 🌄 凤凰山云海清晨预测报告\n"
        for loc, res in all_results.items():
            best = res['best']
            if best and best['index'] > 0:
                status = "🟢 安全" if "🟢" in best['wash_status'] else \
                         "🟡 擦边" if "🟡" in best['wash_status'] else "🔴 洗头"
                msg += (
                    f"**{loc}** (海拔 {res['meta']['elev']}m)\n"
                    f"├── 最佳时间: {best['dt'].strftime('%m-%d %H:%M')} | 日出: {res['sunrise']}\n"
                    f"├── 云海指数: {best['index']}/100 | 云底: {best['cloud_base']:.0f}m\n"
                    f"└── 风险状态: {status}\n\n"
                )
        
        try:
            resp = requests.post(self.PUSH_URL, json={
                "token": PUSH_PLUS_TOKEN, "title": "🏔️ 云海预测通知", 
                "content": msg, "template": "markdown"
            }, timeout=10)
            if resp.json().get('code') == 200:
                print("\n🚀 微信推送发送成功！请留意手机消息。")
            else:
                print(f"\n❌ 推送失败，请检查 token。错误信息: {resp.text}")
        except Exception as e:
            print(f"\n❌ 推送请求异常: {e}")


if __name__ == "__main__":
    locations = [
        '潮安区坪坑头村', '宋茶文化博物馆', '双髻娘山', '无水坳',
        '梅州鸿图嶂景区', '潮安区崧顶茗宿东北', '望岭村民委员会', '鸳鸯寨'
    ]
    analyzer = CloudSeaAnalyzerPro(locations)
    analyzer.analyze()