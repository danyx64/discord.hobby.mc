from .hierarchyadmin_v3 import HierarchyAdmin


async def setup(bot):
    await bot.add_cog(HierarchyAdmin(bot))
