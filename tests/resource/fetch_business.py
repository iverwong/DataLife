"""获取主营构成接口的真实响应数据."""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.resource.manager import ResourceManager, ResourceType
from core.data.business import get_business


async def fetch_and_save():
    """执行真实请求并保存响应."""
    print("开始获取主营构成数据...")

    try:
        # 使用真实股票代码获取数据
        stock_code = "000001"  # 平安银行
        business_data = await get_business(stock_code)

        # 使用ResourceManager保存资源
        manager = ResourceManager()
        manager.save(
            name="business_000001",
            data=business_data,
            resource_type=ResourceType.RESPONSE,
            version="1.0.0",
            description=f"{stock_code}股票的主营构成真实数据",
            source="AkShare stock_zygc_em 接口",
            tags=["business", "akshare", "external"],
        )

        print(f"Resource saved: business_000001.pkl")
        print(f"报告日期: {business_data.report_date}")
        print(f"行业分类数据行数: {len(business_data.industry_df)}")
        print(f"产品分类数据行数: {len(business_data.product_df)}")
        print(f"地区分类数据行数: {len(business_data.region_df)}")

    except Exception as e:
        print(f"获取数据失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(fetch_and_save())
