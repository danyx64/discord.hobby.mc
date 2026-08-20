from .hierarchyadmin_v2 import HierarchyAdmin


async def setup(bot):
    await bot.add_cog(HierarchyAdmin(bot))
