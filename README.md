# Ticket Helper

一个保守的个人购票辅助脚本模板。它会打开真实浏览器，复用你的登录态，按配置监控页面状态，发现可购按钮后提醒并辅助进入确认页；默认会在支付或最终提交前停住，由你人工确认。

它不包含绕过验证码、破解签名、抓包复用接口、高频压测或自动支付逻辑。请只在目标网站规则允许的范围内使用。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 配置

```bash
cp config.example.yaml config.yaml
```

然后编辑 `config.yaml`：

- `target.url`: 售票详情页地址
- `target.sale_time`: 开售时间，格式为 `YYYY-MM-DD HH:MM:SS`
- `selectors.available_button`: 可购买按钮
- `selectors.sold_out_text`: 售罄/缺货状态
- `selectors.date_option`: 日期选项，留空则不选
- `selectors.price_option`: 票档选项，留空则不选
- `purchase.quantity`: 购票数量

Playwright 支持 CSS 选择器，也支持 `text=立即购买` 这类文本选择器。

## 先保存登录态

```bash
python ticket_helper.py --login-only -c config.yaml
```

浏览器打开后手动登录，登录成功后回到终端按 Enter。登录态会保存在 `.browser-profile/`。

## 开始监控

```bash
python ticket_helper.py -c config.yaml
```

发现可购状态后，脚本会发出终端提示音，进入下一步页面，并默认停在人工确认位置。

## 选择器怎么找

打开目标页面，右键按钮或票档，选择“检查”，复制稳定的 CSS 选择器。优先使用稳定属性，例如：

```yaml
selectors:
  available_button: "button:has-text('立即购买')"
  price_option: "text=580元"
  date_option: "text=2026-06-03"
```

如果网站 DOM 经常变化，文本选择器通常比一长串 `div > div > ...` 更耐用。
