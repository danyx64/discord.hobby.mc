from .ageguard import AgeGuard


async def setup(bot):
    await bot.add_cog(AgeGuard(bot))
