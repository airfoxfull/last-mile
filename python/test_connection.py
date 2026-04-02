"""快速验证 Clawith 连通性"""

import asyncio
import sys
sys.path.insert(0, ".")

from src.clawith import client


async def main():
    # 1. 登录
    print("[test] 登录...")
    data = await client.login("296105415@qq.com", "Aa123456")
    print(f"[test] 登录成功，role={data['user']['role']}")

    # 2. 列出 Agent
    print("[test] 列出 Agent...")
    agents = await client.list_agents()
    for a in agents:
        print(f"  {a['name']}: {a['id']}")

    # 3. 找到 Planner
    planner = next((a for a in agents if a["name"] == "Planner"), None)
    if not planner:
        print("[test] 未找到 Planner Agent!")
        return

    # 4. 读 soul.md
    print(f"[test] 读 Planner soul.md...")
    soul = await client.read_file(planner["id"], "soul.md")
    print(f"  soul.md 前 100 字: {soul[:100]}")

    # 5. 发消息测试
    print(f"[test] 发消息给 Planner...")
    reply = await client.send_message(planner["id"], "你好，用一句话介绍你自己")
    print(f"[test] Planner 回复: {reply[:200]}")

    print("\n[test] ✅ 全部通过！")


if __name__ == "__main__":
    asyncio.run(main())
