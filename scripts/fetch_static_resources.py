"""
获取静态资源脚本

获取阳光电源(300274)的真实数据并保存为测试静态资源
"""

import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import akshare as ak  # pyright: ignore[reportMissingTypeStubs]
import httpx

from core.data.announcement import Announcement
from core.data.models import AnnouncementItem, AnnouncementsResponse
from tests.resource.manager import ResourceType, resource_manager


def fetch_business_data() -> None:
    """获取主营业务数据"""
    print("正在获取阳光电源(300274)主营业务数据...")
    code = "SZ300274"
    df = ak.stock_zygc_em(code)  # pyright: ignore[reportUnknownMemberType]
    print(f"获取到 {len(df)} 行数据")
    print(f"列名: {df.columns.tolist()}")  # pyright: ignore[reportUnknownMemberType]
    print(f"报告日期范围: {df['报告日期'].min()} ~ {df['报告日期'].max()}")  # pyright: ignore[reportUnknownMemberType]

    _ = resource_manager.save(
        name="ygdq_300274_business",
        data=df,
        resource_type=ResourceType.DATAFRAME,
        version="1.0.0",
        description="阳光电源(300274)主营业务构成数据",
        source="akshare.stock_zygc_em(SZ300274)",
        tags=["akshare", "business", "300274", "阳光电源"],
    )
    print("主营业务数据已保存")


async def fetch_announcements_data() -> None:
    """获取公告数据"""
    print("\n正在获取阳光电源公告数据...")

    # 先获取股票映射
    from core.data.announcement import _get_stock_json

    stock_json = await _get_stock_json()
    print(f"股票映射获取成功，共 {len(stock_json)} 只股票")

    # 获取最近90天的公告（扩大范围确保有数据）
    end_date = date.today() + timedelta(days=1)
    start_date = end_date - timedelta(days=90)

    # 保存原始HTTP响应（用于mock）
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    stock_item = f"300274,{stock_json['300274']}"
    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_item,
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start_date}~{end_date}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(url, data=payload)
        response_data: dict[str, object] = res.json()  # pyright: ignore[reportExplicitAny]

    response = AnnouncementsResponse.model_validate(response_data)
    announcements_list = response.announcements or []
    print(f"API返回公告数量: {len(announcements_list)}")

    _ = resource_manager.save(
        name="ygdq_300274_announcements_response",
        data=response_data,
        resource_type=ResourceType.JSON,
        version="1.0.0",
        description="阳光电源(300274)公告API原始响应",
        source="cninfo.com.cn/new/hisAnnouncement/query",
        tags=["cninfo", "api_response", "300274", "mock"],
    )
    print("API响应数据已保存")

    # 过滤并转换为 Announcement 对象
    filtered_keywords = ["摘要", "英文版", "图文版"]
    filtered: list[AnnouncementItem] = [
        item
        for item in announcements_list
        if not any(kw in item.announcementTitle for kw in filtered_keywords)
    ]

    result = [
        Announcement(
            id=item.announcementId,
            stock=item.secCode,
            title=f"{item.secName}({item.secCode})-{item.announcementTitle}",
            size=item.adjunctSize,
            url=f"https://static.cninfo.com.cn/{item.adjunctUrl}",
            published_date=datetime.fromtimestamp(item.announcementTime / 1000),
        )
        for item in filtered
    ]

    print(f"解析后公告数量: {len(result)}")

    _ = resource_manager.save(
        name="ygdq_300274_announcements",
        data=result,
        resource_type=ResourceType.PICKLE,
        version="1.0.0",
        description="阳光电源(300274)最近30天公告列表",
        source=f"cninfo.com.cn hisAnnouncement query ({start_date} ~ {end_date})",
        tags=["cninfo", "announcements", "300274", "阳光电源"],
    )
    print("公告数据已保存")


async def main() -> None:
    """主函数"""
    print("=" * 50)
    print("开始获取静态资源")
    print("=" * 50)

    # 获取主营业务数据
    fetch_business_data()

    # 获取公告数据
    await fetch_announcements_data()

    print("\n" + "=" * 50)
    print("所有静态资源保存完成！")
    print("=" * 50)

    # 列出所有资源
    print("\n已保存的资源列表:")
    for name in resource_manager.list_resources():
        meta = resource_manager.get_meta(name)
        print(f"  - {name}: {meta.description} (v{meta.version})")


if __name__ == "__main__":
    asyncio.run(main())
