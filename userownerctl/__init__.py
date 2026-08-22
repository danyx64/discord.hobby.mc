from .userownerctl import UserOwnerControl


async def setup(bot):
    await bot.add_cog(UserOwnerControl(bot))
