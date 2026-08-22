from .userinstallctl import UserInstallControl


async def setup(bot):
    await bot.add_cog(UserInstallControl(bot))
