import asyncio
import copy
import json

import discord
import tabulate
from redbot.core import commands
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate

from .abc import MixinMeta
from .converters import Args
from .functions import chunks
from .menus import GenericMenu, PokedexFormat, PokeList, PokeListMenu, SearchFormat
from .pokemixin import poke
from .statements import *

_ = Translator("Pokecord", __file__)


class GeneralMixin(MixinMeta):
    """Pokecord General Commands"""

    @commands.max_concurrency(1, commands.BucketType.user)
    @commands.command(name="list", aliases=["pokemon"])
    async def _list(self, ctx, user: discord.Member = None):
        """List a trainers or your own pokémon!"""
        conf = await self.user_is_global(ctx.author)
        if not await conf.has_starter():
            return await ctx.send(
                _(
                    "You haven't picked a starter pokemon yet! Check out {prefix} before trying to list your pokemon."
                ).format(prefix=ctx.clean_prefix)
            )
        user = user or ctx.author
        async with ctx.typing():
            result = self.cursor.execute(SELECT_POKEMON, (user.id,)).fetchall()
        pokemons = []
        for i, data in enumerate(result, start=1):
            poke = json.loads(data[0])
            poke["sid"] = i
            pokemons.append(poke)
        if not pokemons:
            return await ctx.send(_("You don't have any pokémon, go get catching trainer!"))
        _id = await conf.pokeid()
        await ctx.send(
            _("{user}'s selected Pokémon ID is {id}").format(user=user, id=_id),
            delete_after=5,
        )
        await PokeListMenu(
            source=PokeList(pokemons),
            cog=self,
            ctx=ctx,
            user=user,
            delete_message_after=False,
        ).start(ctx=ctx, wait=False)

    @commands.max_concurrency(1, commands.BucketType.user)
    @poke.command()
    async def nick(self, ctx, id: int, *, nickname: str):
        """Set a pokémons nickname.

        ID refers to the position within your pokémon listing.
        This is found at the bottom of the pokemon on `[p]list`"""
        conf = await self.user_is_global(ctx.author)
        if not await conf.has_starter():
            return await ctx.send(
                _(
                    "You haven't picked a starter pokemon yet! Check out {prefix} before trying to nickname a pokemon."
                ).format(prefix=ctx.clean_prefix)
            )
        if id <= 0:
            return await ctx.send(_("The ID must be greater than 0!"))
        if len(nickname) > 40:
            await ctx.send(
                "The nickname you have specified is too big. It must be under 40 characters."
            )
            return
        async with ctx.typing():
            result = self.cursor.execute(
                SELECT_POKEMON,
                (ctx.author.id,),
            ).fetchall()
        pokemons = [None]
        for data in result:
            pokemons.append([json.loads(data[0]), data[1]])
        if not pokemons:
            return await ctx.send(_("You don't have any pokémon, trainer!"))
        if id > len(pokemons):
            return await ctx.send(
                _(
                    "You don't have a pokemon at that slot.\nID refers to the position within your pokémon listing.\nThis is found at the bottom of the pokemon on `[p]list`"
                )
            )
        pokemon = pokemons[id]
        pokemon[0]["nickname"] = nickname
        self.cursor.execute(
            UPDATE_POKEMON,
            (ctx.author.id, pokemon[1], json.dumps(pokemon[0])),
        )
        await ctx.send(
            _("Your {pokemon} has been nicknamed `{nickname}`").format(
                pokemon=self.get_name(pokemon[0]["name"], ctx.author), nickname=nickname
            )
        )

    @commands.max_concurrency(1, commands.BucketType.user)
    @poke.command(aliases=["free"])
    async def release(self, ctx, id: int):
        """Release a pokémon."""
        conf = await self.user_is_global(ctx.author)
        if not await conf.has_starter():
            return await ctx.send(
                _(
                    "You haven't picked a starter pokemon yet! Check out {prefix} before trying to release a pokemon."
                ).format(prefix=ctx.clean_prefix)
            )
        if id <= 0:
            return await ctx.send(_("The ID must be greater than 0!"))
        async with ctx.typing():
            result = self.cursor.execute(
                SELECT_POKEMON,
                (ctx.author.id,),
            ).fetchall()
        pokemons = [None]
        for data in result:
            pokemons.append([json.loads(data[0]), data[1]])
        if not pokemons:
            return await ctx.send(_("You don't have any pokémon, trainer!"))
        if id >= len(pokemons):
            return await ctx.send(
                _(
                    "You don't have a pokemon at that slot.\nID refers to the position within your pokémon listing.\nThis is found at the bottom of the pokemon on `[p]list`"
                )
            )
        pokemon = pokemons[id]
        name = self.get_name(pokemon[0]["name"], ctx.author)
        await ctx.send(
            _(
                "You are about to free {name}, if you wish to continue type `yes`, otherwise type `no`."
            ).format(name=name)
        )
        try:
            pred = MessagePredicate.yes_or_no(ctx, user=ctx.author)
            await ctx.bot.wait_for("message", check=pred, timeout=20)
        except asyncio.TimeoutError:
            await ctx.send("Exiting operation.")
            return

        if pred.result:
            msg = ""
            userconf = await self.user_is_global(ctx.author)
            pokeid = await userconf.pokeid()
            if id < pokeid:
                msg += _(
                    "\nYour default pokemon may have changed. I have tried to account for this change."
                )
                await userconf.pokeid.set(pokeid - 1)
            elif id == pokeid:
                msg += _(
                    "\nYou have released your selected pokemon. I have reset your selected pokemon to your first pokemon."
                )
                await userconf.pokeid.set(1)
            self.cursor.execute(
                "DELETE FROM users where message_id = ?",
                (pokemon[1],),
            )
            await ctx.send(_("Your {name} has been freed.{msg}").format(name=name, msg=msg))
        else:
            await ctx.send(_("Operation cancelled."))

    @commands.max_concurrency(1, commands.BucketType.user)
    @commands.command(usage="id_or_latest")
    @commands.guild_only()
    async def select(self, ctx, _id: Union[int, str]):
        """Select your default pokémon."""
        conf = await self.user_is_global(ctx.author)
        if not await conf.has_starter():
            return await ctx.send(
                _(
                    "You haven't chosen a starter pokemon yet, check out `{prefix}starter` for more information."
                ).format(prefix=ctx.clean_prefix)
            )
        async with ctx.typing():
            result = self.cursor.execute(
                """SELECT pokemon, message_id from users where user_id = ?""",
                (ctx.author.id,),
            ).fetchall()
            pokemons = [None]
            for data in result:
                pokemons.append([json.loads(data[0]), data[1]])
            if not pokemons:
                return await ctx.send(_("You don't have any pokemon to select."))
            if isinstance(_id, str):
                if _id == "latest":
                    _id = len(pokemons) - 1
                else:
                    await ctx.send(
                        _("Unidentified keyword, the only supported action is `latest` as of now.")
                    )
                    return
            if _id < 1 or _id > len(pokemons) - 1:
                return await ctx.send(
                    _(
                        "You've specified an invalid ID.\nID refers to the position within your pokémon listing.\nThis is found at the bottom of the pokemon on `[p]list`"
                    )
                )
            await ctx.send(
                _("You have selected {pokemon} as your default pokémon.").format(
                    pokemon=self.get_name(pokemons[_id][0]["name"], ctx.author)
                )
            )
        conf = await self.user_is_global(ctx.author)
        await conf.pokeid.set(_id)
        await self.update_user_cache()

    @commands.command()
    @commands.max_concurrency(1, commands.BucketType.user)
    async def pokedex(self, ctx):
        """Check your caught pokémon!"""
        async with ctx.typing():
            pokemons = await self.config.user(ctx.author).pokeids()
            pokemonlist = copy.deepcopy(self.pokemonlist)
            for i, pokemon in enumerate(pokemonlist, start=1):
                if str(pokemon) in pokemons:
                    pokemonlist[i]["amount"] = pokemons[str(pokemon)]
            a = [value for value in pokemonlist.items()]
            chunked = []
            total = 0
            page = 1
            for item in chunks(a, 20):
                chunked.append(item)
            await GenericMenu(
                source=PokedexFormat(chunked),
                delete_message_after=False,
                cog=self,
                len_poke=len(pokemonlist),
            ).start(
                ctx=ctx,
                wait=False,
            )

    @commands.command()
    async def psearch(self, ctx, *, args: Args):
        """Search your pokemon.

        Arguements must have `--` before them.
            `--name` | `--n` - Search pokemon by name.
            `--level`| `--l` - Search pokemon by level.
            `--id`   | `--i` - Search pokemon by ID.
            `--variant`   | `--v` - Search pokemon by variant.
        """
        async with ctx.typing():
            result = self.cursor.execute(
                """SELECT pokemon, message_id from users where user_id = ?""",
                (ctx.author.id,),
            ).fetchall()
            if not result:
                await ctx.send(_("You don't have any pokémon trainer!"))
            pokemons = [None]
            for data in result:
                pokemons.append([json.loads(data[0]), data[1]])
            correct = ""
            for poke in pokemons[1:]:
                name = self.get_name(poke[0]["name"], ctx.author)
                if args["names"]:
                    if name.lower() == args["names"].lower():
                        correct += _("{pokemon} | Level: {level} | ID: {id}\n").format(
                            pokemon=name, level=poke[0]["level"], id=poke[0]["id"]
                        )
                elif args["level"]:
                    if poke[0]["level"] == args["level"][0]:
                        correct += _("{pokemon} | Level: {level} | ID: {id}\n").format(
                            pokemon=name, level=poke[0]["level"], id=poke[0]["id"]
                        )
                elif args["id"]:
                    if poke[0]["id"] == args["id"][0]:
                        correct += _("{pokemon} | Level: {level} | ID: {id}\n").format(
                            pokemon=name, level=poke[0]["level"], id=poke[0]["id"]
                        )
                elif args["variant"]:
                    if poke[0].get("variant", "None").lower() == args["variant"].lower():
                        correct += _("{pokemon} | Level: {level} | ID: {id}\n").format(
                            pokemon=name, level=poke[0]["level"], id=poke[0]["id"]
                        )

            if not correct:
                await ctx.send("No pokémon returned for that search.")
                return
            content = list(pagify(correct, page_length=1024))
            await GenericMenu(
                source=SearchFormat(content),
                delete_message_after=False,
            ).start(ctx=ctx, wait=False)

    @commands.command()
    @commands.max_concurrency(1, commands.BucketType.user)
    async def current(self, ctx):
        """Show your current selected pokemon"""
        conf = await self.user_is_global(ctx.author)
        if not await conf.has_starter():
            return await ctx.send(
                _(
                    "You haven't picked a starter pokemon yet! Check out {prefix} before trying to list your pokemon."
                ).format(prefix=ctx.clean_prefix)
            )
        user = ctx.author
        async with ctx.typing():
            result = self.cursor.execute(SELECT_POKEMON, (user.id,)).fetchall()
        pokemons = []
        for i, data in enumerate(result, start=1):
            poke = json.loads(data[0])
            poke["sid"] = i
            pokemons.append(poke)
        if not pokemons:
            return await ctx.send(_("You don't have any pokémon, go get catching trainer!"))
        _id = await conf.pokeid()
        try:
            pokemon = pokemons[_id - 1]
        except IndexError:
            await ctx.send(
                _(
                    "An error occured trying to find your pokemon at slot {slotnum}\nAs a result I have set your default pokemon to 1."
                ).format(slotnum=_id)
            )
            await conf.pokeid.set(1)
            return
        else:
            stats = pokemon["stats"]
            ivs = pokemon["ivs"]
            pokestats = tabulate.tabulate(
                [
                    [_("HP"), stats["HP"], ivs["HP"]],
                    [_("Attack"), stats["Attack"], ivs["Attack"]],
                    [_("Defence"), stats["Defence"], ivs["Defence"]],
                    [_("Sp. Atk"), stats["Sp. Atk"], ivs["Sp. Atk"]],
                    [_("Sp. Def"), stats["Sp. Def"], ivs["Sp. Def"]],
                    [_("Speed"), stats["Speed"], ivs["Speed"]],
                ],
                headers=[_("Stats"), _("Value"), _("IV")],
            )
            nick = pokemon.get("nickname")
            alias = _("**Nickname**: {nick}\n").format(nick=nick) if nick is not None else ""
            variant = (
                _("**Variant**: {variant}\n").format(variant=pokemon.get("variant"))
                if pokemon.get("variant")
                else ""
            )
            types = ", ".join(pokemon["type"])
            desc = _(
                "**ID**: {id}\n{alias}**Level**: {level}\n**Type**: {type}\n**Gender**: {gender}\n**XP**: {xp}/{totalxp}\n{variant}{stats}"
            ).format(
                id=f"#{pokemon.get('id')}" if pokemon.get("id") else "0",
                alias=alias,
                level=pokemon["level"],
                type=types,
                gender=pokemon.get("gender", "N/A"),
                variant=variant,
                xp=pokemon["xp"],
                totalxp=self.calc_xp(pokemon["level"]),
                stats=box(pokestats, lang="prolog"),
            )
            embed = discord.Embed(
                title=self.get_name(pokemon["name"], ctx.author)
                if not pokemon.get("alias", False)
                else pokemon.get("alias"),
                description=desc,
            )
            _file = discord.File(
                self.datapath
                + f'/pokemon/{pokemon["name"]["english"] if not pokemon.get("variant") else pokemon.get("alias") if pokemon.get("alias") else pokemon["name"]["english"]}.png',
                filename="pokemonspawn.png",
            )
            embed.set_thumbnail(url="attachment://pokemonspawn.png")
            embed.set_footer(text=_("Pokémon ID: {number}").format(number=pokemon["sid"]))
            await ctx.send(embed=embed, file=_file)
