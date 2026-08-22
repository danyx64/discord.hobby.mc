from .ownercontrol import OwnerControl


async def setup(bot):
    await bot.add_cog(OwnerControl(bot))
