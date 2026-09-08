from .extsrv import ExtSrv


async def setup(bot):
    await bot.add_cog(ExtSrv(bot))
