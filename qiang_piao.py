import time
import random
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError

# ==============================================================================
# 模块一：全局数据配置结构 (Data Configuration Model)
# ==============================================================================
from config import TICKET_AUTOMATION_CONFIG


class TrainTicketAutomator:
    """
    基于Playwright引擎的端到端自动化票务处理中枢
    具备高频查询、防风控、自动跳过无票选项及自愈重试能力
    """

    def __init__(self, playwright, config: Dict):
        self.config = config
        self.browser = playwright.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )

        try:
            self.context: BrowserContext = self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                storage_state="auth_state.json",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            print("INFO: 成功加载本地 auth_state.json 会话凭证缓存。")
        except Exception:
            self.context: BrowserContext = self.browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            print("WARNING: 会话缓存缺失。本次执行将回退至未登录的匿名状态。")

        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        self.page: Page = self.context.new_page()

    def generate_jitter_delay(self) -> float:
        """生成带有微小随机抖动的防风控延迟时间"""
        base = self.config["base_poll_interval"]
        jitter = random.uniform(0.1, 0.4)
        return base + jitter

    def inject_search_parameters(self) -> None:
        """利用 URL 参数空降查票页，规避下拉框Bug"""
        date = self.config['travel_date']
        from_st = self.config['departure_station']
        from_cd = self.config['departure_code']
        to_st = self.config['arrival_station']
        to_cd = self.config['arrival_code']

        print(f"INFO: 正在直接空降至 {date} 的查票页面...")
        direct_url = f"https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc&fs={from_st},{from_cd}&ts={to_st},{to_cd}&date={date}&flag=N,N,Y"

        self.page.goto(direct_url)
        self.page.wait_for_load_state("networkidle")
        print("INFO: 页面直达成功，即将进入高频监听队列。")

    def execute_high_frequency_polling(self) -> Optional[Page]:
        """核心轮询引擎：寻找并点击可用车次"""
        query_button = self.page.locator("#query_ticket")

        while True:
            try:
                query_button.click(force=True)
                self.page.wait_for_selector("#queryLeftTable tr", state="attached", timeout=8000)

                for target_train in self.config["target_trains"]:
                    train_row_xpath = f"//tr[.//a[contains(text(), '{target_train}')]]"

                    if self.page.locator(train_row_xpath).count() > 0:
                        train_row = self.page.locator(train_row_xpath).first
                        booking_btn = train_row.locator("a.btn72")

                        if booking_btn.is_visible() and "btn_no_res" not in (booking_btn.get_attribute("class") or ""):
                            print(f"SUCCESS: 目标车次 [{target_train}] 发现可用库存！执行越权夺取...")

                            with self.context.expect_page() as new_page_event:
                                booking_btn.click()

                            return new_page_event.value
                        else:
                            print(f"DEBUG: 车次 [{target_train}] 暂时无票或尚未开售。")
                    else:
                        print(f"DEBUG: 当前视图中未解析到车次节点 [{target_train}]。")

            except PlaywrightTimeoutError:
                print("WARNING: DOM节点监听超时，引擎将自动触发状态恢复机制。")

            time.sleep(self.generate_jitter_delay())

    def process_order_submission(self, order_page: Page) -> bool:
        """
        订单组装与防熔断引擎：
        返回 True: 抢票彻底成功，进入付款环节
        返回 False: 遭遇无票熔断，要求外层循环立刻重试
        """
        try:
            print("INFO: 引擎已挂载至订单确认子系统...")
            order_page.wait_for_load_state("domcontentloaded")
            order_page.wait_for_selector("#normal_passenger_id", timeout=10000)

            # 乘车人智能勾选
            for passenger_name in self.config["passengers"]:
                semantic_label = order_page.locator(f"label:has-text('{passenger_name}')").first
                if semantic_label.is_visible():
                    checkbox_locator = semantic_label.locator("xpath=..").locator("input[type='checkbox']")
                    if not checkbox_locator.is_checked():
                        checkbox_locator.check(force=True)
                        print(f"SUCCESS: 乘车人 [{passenger_name}] 勾选完成。")
                else:
                    print(f"CRITICAL: 找不到乘车人 [{passenger_name}]！")

            # 点击提交订单
            submit_button = order_page.locator("#submitOrder_id")
            if submit_button.is_visible():
                submit_button.click()
                print("INFO: 一级订单提交完毕，正在分析系统排队反馈...")

                # 【防熔断核心逻辑】：循环检测最终确认按钮 or 失败返回按钮
                confirm_btn = order_page.locator("#qr_submit_id")
                reject_btn = order_page.locator("a:has-text('返回修改')")

                # 最多等待 15 秒来获取排队判定结果
                for _ in range(30):
                    if reject_btn.is_visible():
                        print("❌ 触发系统熔断：排队人数已超过余票！正在丢弃此订单并立刻返回重新抢票...")
                        order_page.close()  # 摧毁无用的新标签页
                        return False  # 向上级返回 False，触发重试

                    if confirm_btn.is_visible():
                        confirm_btn.click()
                        print("🎉🎉🎉 SUCCESS: 订单已成功提交至中央排队队列！大局已定！哈！不愧是咱俩！")
                        print("👉 【请立刻人工接管浏览器】：等待页面排队圈圈转完，出现二维码后请立刻扫码付款！")
                        order_page.wait_for_timeout(600000)  # 提供 15 分钟时间让你扫码付款
                        return True

                    time.sleep(0.5)

                print("WARNING: 未捕获到排队状态反馈，可能网络极度拥堵。")
                order_page.close()
                return False

        except Exception as generic_exception:
            print(f"ERROR: 订单引擎发生异常: {str(generic_exception)}。将自动退回重试。")
            try:
                order_page.close()
            except:
                pass
            return False

        return False

    def dispatch(self) -> None:
        """具备不死闭环的主控调度函数"""
        # 1. 强制前往登录页面
        self.page.goto("https://kyfw.12306.cn/otn/resources/login.html")
        print("👉 请在弹出的浏览器中手动扫码登录。")

        # 2. 暂停点
        input("✅ 扫码登录成功，且页面跳到【个人中心】后，请在这里按【回车键】继续...")

        # 3. 注入抢票参数
        self.inject_search_parameters()

        # 4. 永不宕机的抢票死循环
        while True:
            # 去找票
            active_order_page = self.execute_high_frequency_polling()
            if active_order_page:
                # 找到票就提交
                is_payment_ready = self.process_order_submission(active_order_page)

                if is_payment_ready:
                    print("✅ 任务完成！祝您旅途愉快！")
                    break  # 只有真正走到付款排队那一步，循环才会跳出
                else:
                    print("🔄 呦呵，我还不信了准备发起下一轮极速猛攻...")
                    time.sleep(1)  # 短暂喘息防止断流，随后立刻重试

    def teardown(self) -> None:
        """销毁测试环境容器"""
        self.browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright_instance:
        automation_kernel = TrainTicketAutomator(playwright_instance, TICKET_AUTOMATION_CONFIG)
        try:
            automation_kernel.dispatch()
        finally:
            pass
