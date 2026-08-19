from .serverlogger_v3 import ServerLogger


async def setup(bot):
    await bot.add_cog(ServerLogger(bot))
