from .leaveplain import LeavePlain


async def setup(bot):
    await bot.add_cog(LeavePlain(bot))
