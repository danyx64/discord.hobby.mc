from .serverlogger import ServerLogger


async def setup(bot):
    await bot.add_cog(ServerLogger(bot))
