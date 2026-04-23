from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import random
import config
from config import wolf_wrap

MUSIC_PICKS = [
    "🎵 She Wolf (Falling To Pieces) — David Guetta ft. Sia",
    "🎵 Get Out Here — Wiquez",
]

WOLF_FACTS = [
    "Wolves can hear sounds up to 10 miles away in open terrain.",
    "A wolf's howl can be heard up to 10 miles away.",
    "Wolves mate for life and live in tight family packs.",
    "The average wolf pack consists of 5 to 10 wolves.",
    "Wolves can run at speeds of up to 35–40 mph in short bursts.",
    "Wolves have 42 teeth, including four canines.",
    "A wolf's sense of smell is 100 times stronger than a human's.",
    "Wolves are keystone species — removing them collapses ecosystems.",
    "Wolf pups are born blind and deaf, fully dependent on the pack.",
    "Wolves communicate through howls, body language, and scent marking.",
    "The Czechoslovakian Wolfdog was bred from German Shepherds and Carpathian wolves.",
    "Wolves can travel up to 30 miles a day while hunting.",
    "Alpha wolves don't dominate through aggression — they lead through experience.",
    "Wolves have two layers of fur — a dense undercoat and a longer topcoat.",
    "A wolf pack's territory can range from 50 to over 1000 square miles.",
]

WOLF_MEMORIES = [
    "Frost moved ahead of the group without a word — three seconds later, they all understood why.",
    "Ember hit the flank before Wolfy even called it. Pack Resonance at its cleanest.",
    "Sarah stood between the pack and something none of them fully understood yet. She didn't move.",
    "Thorn said nothing. He just shifted his weight to the rear and the line held.",
    "Kael's eyes shifted to ember once. That was enough. Whatever was coming stopped.",
    "Ash didn't fight. She steadied. And somehow that mattered more.",
    "Shadow handled it before it reached the pack. No one asked how.",
    "The Frost Moon came in quiet. Wolfy felt the precision before he understood what to do with it.",
    "Pack Resonance held longer than it should have. Kael paid for it afterward — they all knew.",
    "Under the Blood Moon, instinct led. Control followed, barely.",
    "The sigil pulsed once, slow and deliberate. Wolfy didn't act on it. He waited. That was the right call.",
    "Wolfy moved through the treeline without sound. Scout Alpha doesn't announce itself.",
    "The Golden Moon made leaving feel impossible. The pack felt it too.",
    "Emerald Moon hit Kael harder than expected. Wolfy stayed close.",
    "Trust isn't handed out in this pack. It's earned through moments exactly like this one.",
    "Ash moved through the pack before the argument started. By the time it was over, no one remembered what it was about.",
    "Shadow took the eastern approach. No one told him to. That's why he's on the eastern approach.",
    "Wolfy held the sigil still under the Blood Moon. It wanted to respond. He didn't let it.",
    "Pack Resonance came online clean for once — no strain, no drain. Kael looked as surprised as anyone.",
    "Thorn hasn't spoken about what happened at the rear flank. He doesn't need to. The pack saw it.",
    "The Emerald Moon made Kael's glow flicker. Wolfy noticed. Neither of them said anything.",
    "Frost's tracks disappeared at the ridge. He was back at the den before anyone thought to look for him.",
    "Ember called the strike three counts early. She was right. She always is.",
    "Sarah flagged it. Wolfy assessed it. Shadow removed it. The pack moved on.",
    "The Golden Moon pulled hard that night. Even Wolfy felt it — the weight of pack bond in full effect.",
    "Blaze was online at midnight troubleshooting. Two hours. No complaint. That's just how he works.",
    "Matthijs said 'CALL' and two hours later they were still in voice. No plan needed.",
    "Blaze rated the story 10 out of 10 and asked for more. That meant something.",
    "Matthijs shared a song. It wasn't Wolfy's style. He listened anyway. That's the deal.",
    "Distance is just distance. Blaze proved that when he showed up in the Netherlands.",
]

WOLF_DREAMS = [
    "🌑 The Blood Moon bleeds across the sky. Your instincts sharpen past comfortable. Something in you wants to run toward the threat, not away.",
    "❄️ A Frost Moon night — cold and precise. You see everything clearly. You feel nothing pulling you sideways. It's almost too quiet.",
    "🌿 The Emerald Moon rises and something slips. Kael is beside you but his footing feels wrong. You stay closer than usual.",
    "🌕 The Golden Moon. The pack is together and leaving feels genuinely impossible — not from fear, but from bond.",
    "🌑 A charcoal wolf stands at the edge of a ridge. Near-crimson streaks catch the light as it moves. You recognise the stance before the face.",
    "🔥 The sigil on the right shoulder pulses slow and steady. Heat beneath the skin. Something is aligning.",
    "❄️ Frost is already ahead of you on the ridge. He doesn't look back. He doesn't need to.",
    "👁️ Sarah is watching something you can't see yet. She hasn't moved. That means it isn't time yet.",
    "🌑 Pack Resonance hums at the edge of activation. Kael is steady. Everything holds.",
    "🩸 The Blood Moon pulls hard tonight. Control costs something real. You pay it anyway.",
    "🌑 You're standing in the ruins. The pack isn't here. You chose to come alone. You're not sure that was right.",
    "❄️ The Frost Moon strips everything back. No emotion, no noise. Just the path ahead and what needs to be done.",
    "🌿 The Emerald Moon. Kael is somewhere behind you. You can feel the bond pulling, but his signal is unstable.",
    "🌕 Under the Golden Moon, every instinct says stay. The bond is running high. The pack is complete.",
    "🔥 The near-crimson streaks are brighter than usual. The sigil is warm against the shoulder. Something is about to start.",
    "🌑 Shadow is at the perimeter. You can't see him but you know. That's how it works.",
    "👁️ Ember is crouched at the far flank, watching. She hasn't moved yet. That means she's already decided.",
]

WOLF_SIGNS = [
    "🐾 **Single deep pawprint, deliberate stride** — Scout Alpha passed through. Recent, purposeful.",
    "🌿 **Bent grass in a wide arc** — The pack moved through before dawn, spread formation.",
    "🪵 **Claw marks at shoulder height** — Territory marked by something large. This ground is claimed.",
    "🌕 **Long low howl at dusk** — Pack call. Not distress. Rally.",
    "❄️ **Double track, perfectly synced** — Bonded pair moving together. Kael and Wolfy.",
    "🩸 **Red snow near the northern edge** — A hunt ended here. Clean, efficient.",
    "🌑 **Total silence in the forest** — Something apex is nearby. Everything else knows it.",
    "💨 **Near-crimson scent on the wind** — Shadow Crimson Wolf active. Close.",
    "🔥 **Faint heat in the soil at the ridge** — The sigil was active here recently.",
    "👁️ **No tracks, but disturbed air** — Frost came through. You won't find prints.",
    "🤍 **White fur caught on a high branch** — Sarah was on elevated watch. She saw everything.",
    "🌑 **Deep black fur, single strand on bark** — Shadow passed here. Moving with intent.",
    "🔥 **Ember-red streak in the mud** — Ember ran this route at speed. Combat posture.",
    "🛡️ **Scuffed earth at the rear approach** — Thorn held this position. Nothing got through.",
    "🌿 **Crushed herbs near the den entrance** — Ash was working the cohesion. Pack tension was high.",
    "❄️ **Pale silver hair on a cold stone** — Frost scouted this location before dawn. Thorough.",
    "🔊 **Distant howl, single note, cut short** — Something interrupted the call. Pay attention.",
    "🌿 **Green pawprint at the border** — Blaze passed through. Steady stride, no hesitation.",
    "🌕 **Small yellow print near the den entrance** — Matthijs was here. Curious, close, not quite sure where to stand yet.",
]

TRACKS = [
    "🐾 Large prints, confident stride, no hesitation at the fork. Scout Alpha didn't slow down.",
    "🌿 Crushed undergrowth in a deliberate arc — flanking pattern. Someone ran this drill recently.",
    "❄️ Snow tracks from two wolves running in near-perfect sync. They stopped at the same moment.",
    "🪵 Bark stripped clean at shoulder height, three parallel marks. Territorial. Recent.",
    "🌑 The tracks stop at the treeline. No continuation. Whatever it was, it chose to disappear.",
    "💧 Pawprints lead to the river's edge. One set. They don't come back out the same way.",
    "🔥 Soil warmer than the air around it, wolf-paw shaped. The sigil was active here.",
    "🩸 Trail ends abruptly. Clean. Whatever happened here was fast and decided.",
    "🤍 Pale prints in a wide patrol arc. High ground coverage. Sarah ran this route at least twice.",
    "🌑 No visible tracks. The approach path is clean. That's Shadow — he doesn't leave evidence.",
    "🔥 Deep prints, wide stance, forward lean. Ember was in combat posture when she passed through.",
    "❄️ Feather-light prints, evenly spaced, no drag. Frost moves like he doesn't want the ground to notice.",
    "🌿 Two sets of prints, one larger, one lighter. Moving together. Bonded pair on patrol.",
    "🛡️ Heavy rear prints, planted deep. Thorn stood here a long time. He wasn't leaving until it was done.",
    "💨 Prints that start mid-stride — no approach. Whatever made these appeared from somewhere else.",
]

SCOUT_REPORTS = [
    "🔭 Northern ridge clear. Frost ran the perimeter — nothing missed.",
    "⚠️ Eastern treeline: fresh tracks, unknown count, moving toward the valley. Shadow is tracking.",
    "🌫️ Visibility dropping from the west. Wolfy called the pack tighter. Standard fog protocol.",
    "✅ Den perimeter secure. Thorn held the rear all night. No contact.",
    "🚨 Unfamiliar scent on the southern border — controlled, deliberate. Not random passage.",
    "🌙 Night patrol complete. Kael's eyes stayed natural the whole shift. Clean night.",
    "🐦 Birds cleared the north woods fast. Ember already moved to intercept position.",
    "👁️ Sarah flagged something on the western approach. Still assessing. Pack on standby.",
    "❄️ Frost is three sectors ahead of schedule. He found something worth noting — report incoming.",
    "✅ Pack Resonance test complete. Stable activation, clean disengage. Kael held anchor the whole run.",
    "🌑 Shadow confirmed the eastern border is clear. Method unspecified. It's clear.",
    "🔥 Ember ran the combat drill solo. Passed. She didn't need the rest of us for that one.",
    "🌿 Ash ran cohesion check on the pack after last night. Tension levels are down. Bond is holding.",
    "🛡️ Thorn flagged a weak point in the southern perimeter. Already reinforced. He handled it.",
    "⚠️ Blood Moon tonight. Pack on reduced autonomy protocol. Instinct management in effect.",
    "❄️ Frost Moon active. Precision window is open. Wolfy called optional extended patrol.",
    "🌿 Emerald Moon rising. Kael on close watch. Pack staying tight until it passes.",
]

FORTUNES = [
    "Control is the primary resource. Overextension degrades performance rather than amplifying it.",
    "The pack moves as one or it doesn't move at all.",
    "Trust is earned through moments, not words. You'll know when it's real.",
    "The Frost Moon brings clarity. Use it before it passes.",
    "Pack Resonance is powerful but punishing. Know what you're spending before you activate it.",
    "The lone wolf hears things the pack misses. That solitude is a tool, not a flaw.",
    "Curiosity leads. Loyalty follows. Strength protects. In that order.",
    "The sigil doesn't lie. If it pulses, something is aligning — pay attention.",
    "Control over power. Always.",
    "The Blood Moon will pull. Whether you follow it is the actual test.",
    "The pack doesn't have to be in the same country to hold.",
    "Loyalty that crosses distance is worth more than loyalty that never gets tested.",
]

QUOTES = [
    "\"The strength of the pack is the wolf, and the strength of the wolf is the pack.\" — Rudyard Kipling",
    "\"Never give up.\" — Wolfy",
    "\"Curiosity leads, loyalty follows, strength protects.\" — The Diamond Badge",
    "\"More wolf than most dare to see — fierce when needed, playful with the few who earn it.\"",
    "\"Control is the primary resource.\"",
    "\"The wolf on the hill is never as hungry as the wolf climbing the hill.\"",
    "\"Like wolves, we are strongest when we run together.\"",
    "\"Trust earned slowly is worth more than trust given freely.\"",
    "\"A wolf does not concern himself with the opinions of sheep.\"",
]

HUNT_TIPS = [
    "🐺 Move downwind. Predatory Precision starts before the target is visible.",
    "👁️ Scan and Analyze first. Rushing before assessment costs the hunt.",
    "🌿 Use terrain — ridges and treelines give cover and flanking advantage.",
    "🤝 Coordinate flanks. Ember takes the offensive, Frost scouts the approach, Thorn holds the rear.",
    "❄️ In snow, slow down. Frost already taught you this.",
    "🌙 Dawn and dusk are prime windows. Pack Resonance holds best in low ambient pressure.",
    "🔇 Silent Command is a weapon. The pack that moves quiet is the pack that wins.",
    "🎯 Prolonged strain risks tunnel vision and forced withdrawal. Know your limit before you hit it.",
]

HOWLS = [
    "🐺 *AWOOOOOOOO!* — The pack call. It carries.",
    "🌕 *Wolfy lifts his head and lets out a long, resonant howl. Somewhere in the distance, Kael answers.*",
    "🌑 *Short, sharp bark — then a rising howl. The pack knows what it means.*",
    "❄️ *A precise, controlled howl under the Frost Moon. Nothing wasted.*",
    "🔥 *The howl builds from the chest — near-crimson streaks catching the low light as it rises.*",
    "🌿 *Soft and low. A check-in. The pack responds one by one.*",
    "🩸 *Under the Blood Moon, the howl comes out rawer than intended. Still controlled. Barely.*",
]

GROWLS = [
    "😤 *Low, steady growl from deep in the chest. Not a warning — a statement.*",
    "⚠️ *Hackles raised, claws edged near-crimson. This is the last notice.*",
    "🔥 *Short, sharp. The kind that means the next step is already decided.*",
    "🌑 *The growl is barely audible. That's worse. The Shadow Crimson Wolf doesn't need volume.*",
    "❄️ *Clean and controlled. Territory. Claimed. End of conversation.*",
]

SHIFTS = [
    "🌑 The charcoal sets in from the edges first — fur deepening, silver-grey undertones surfacing. The near-crimson streaks appear last, faint in still light, vivid in motion.",
    "🔥 The sigil pulses before anything else. Heat beneath the right shoulder, slow and deliberate. Then the shift follows — unhurried, controlled.",
    "❄️ Under the Frost Moon, the shift is precise and cold. No wasted movement. The Shadow Crimson Wolf steps forward fully formed.",
    "🌕 The claws edge near-crimson first — a constant glow, always there at rest. The rest follows when it needs to.",
    "🩸 Blood Moon shift is harder to control. The instincts arrive before the form settles. Wolfy holds the line. Always.",
    "👁️ Paw pads faint-glowing, pressure building through the ground. The shift is already half-done before the decision is conscious.",
    "🌿 The Emerald Moon makes the shift unpredictable. Wolfy feels it resist. He doesn't force it.",
]

LONE_WOLF = [
    "🌑 Solitude comes from circumstance — irritation, specific moments, necessary distance. It's not permanent. The pack is still there.",
    "❄️ The Scout Alpha works alone sometimes. That's the role. It doesn't mean disconnected.",
    "🌕 Even in solitude, the bond with Kael doesn't go quiet. Pack Resonance doesn't require proximity.",
    "🐾 Lone wolf mode is a tool. Wolfy picks it up and puts it down depending on what the moment needs.",
    "🔥 Fierce with the few who earn it. That's not isolation — that's precision.",
]

OWNER_ID = config.OWNER_ID

FURSONA_NAMES = ["Kael", "Ash", "Frost", "Ember", "Shadow", "Thorn", "Riven", "Dusk", "Slate", "Blaze"]
FURSONA_COATS = [
    "charcoal black with silver-grey undertone",
    "pure white with soft silver streaks",
    "deep black with white and silver streaks",
    "medium grey with ember-red streaks",
    "pale silver-grey with darker streaks",
    "dark brown with ash-grey markings",
    "rust-brown with darker bramble-pattern streaks",
    "obsidian",
    "storm grey",
    "midnight blue-black",
]
FURSONA_EYES = ["deep near-crimson", "pale silver", "ice-white", "golden-amber", "icy-blue", "soft ash-grey", "copper-bronze", "amber", "gold"]
FURSONA_TRAITS = [
    "fiercely loyal, protective to the core",
    "vigilant sentinel, moral compass",
    "imposing, handles threats with aloofness",
    "offensive combat support, sharp instincts",
    "reconnaissance and stealth specialist",
    "stabilizer, holds pack cohesion",
    "defensive rear guard, unwavering",
    "calm under pressure, precise",
    "bold and deliberate",
]
FURSONA_ROLES = ["Scout Alpha", "Sentinel", "Enforcer", "Combat Resonance", "Tracker", "Stabilizer", "Rear Guard", "Caretaker", "Co-Alpha"]

MOODTAIL_RESPONSES = {
    "happy":   "🐺 *wags tail, near-crimson streaks catching the light* The pack is good tonight.",
    "sad":     "🐺 *tail drops low, sigil dims* The den feels heavy.",
    "angry":   "🐺 *tail stiffens, claws edge near-crimson* Something pushed too far.",
    "excited": "🐺 *spins once, tail high* Pack Resonance is up. Everyone feels it.",
    "tired":   "🐺 *tail drags, flops at the ridge* Even the Shadow Crimson Wolf needs rest.",
    "bored":   "🐺 *tail flicks once* Waiting for the hunt to start.",
    "scared":  "🐺 *tail low, moves closer to Kael* Better together.",
    "love":    "🐺 *slow tail wag, nudges closer* Pack bond. Non-optional.",
}


class WolfLore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="wolffact", help="Get a random wolf fact")
    async def wolffact_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(WOLF_FACTS)))

    @app_commands.command(name="wolffact", description="Get a random wolf fact", extras={"category": "general"})
    async def wolffact_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(WOLF_FACTS)), ephemeral=ephemeral)

    @commands.command(name="wolfmemory", help="Get a random story excerpt")
    async def wolfmemory_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(WOLF_MEMORIES)))

    @app_commands.command(name="wolfmemory", description="Get a random story excerpt", extras={"category": "general"})
    async def wolfmemory_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(WOLF_MEMORIES)), ephemeral=ephemeral)

    @commands.command(name="wolfdream", help="Get a random wolfy vision or story")
    async def wolfdream_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(WOLF_DREAMS)))

    @app_commands.command(name="wolfdream", description="Get a random wolfy vision or story", extras={"category": "general"})
    async def wolfdream_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(WOLF_DREAMS)), ephemeral=ephemeral)

    @commands.command(name="wolfsign", help="Learn about wolf tracks or calls")
    async def wolfsign_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(WOLF_SIGNS)))

    @app_commands.command(name="wolfsign", description="Learn about wolf tracks or calls", extras={"category": "general"})
    async def wolfsign_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(WOLF_SIGNS)), ephemeral=ephemeral)

    @commands.command(name="track", help="Get a wolf tracking clue or lore snippet")
    async def track_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(TRACKS)))

    @app_commands.command(name="track", description="Get a wolf tracking clue or lore snippet", extras={"category": "general"})
    async def track_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(TRACKS)), ephemeral=ephemeral)

    @commands.command(name="scout", help="Get a scout report or trivia")
    async def scout_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(SCOUT_REPORTS)))

    @app_commands.command(name="scout", description="Get a scout report or trivia", extras={"category": "general"})
    async def scout_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(SCOUT_REPORTS)), ephemeral=ephemeral)

    @commands.command(name="fortune", help="Get a wolf-themed fortune")
    async def fortune_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(FORTUNES)))

    @app_commands.command(name="fortune", description="Get a wolf-themed fortune", extras={"category": "general"})
    async def fortune_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(FORTUNES)), ephemeral=ephemeral)

    @commands.command(name="quote", help="Get a wolf or nature quote")
    async def quote_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(QUOTES)))

    @app_commands.command(name="quote", description="Get a wolf or nature quote", extras={"category": "general"})
    async def quote_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(QUOTES)), ephemeral=ephemeral)

    @commands.command(name="hunttips", help="Get survival or hunting tips")
    async def hunttips_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(HUNT_TIPS)))

    @app_commands.command(name="hunttips", description="Get survival or hunting tips", extras={"category": "general"})
    async def hunttips_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(HUNT_TIPS)), ephemeral=ephemeral)

    @commands.command(name="howl", help="Let out a howl!")
    async def howl_prefix(self, ctx):
        await ctx.send(random.choice(HOWLS))

    @app_commands.command(name="howl", description="Let out a howl!", extras={"category": "general"})
    async def howl_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(random.choice(HOWLS), ephemeral=ephemeral)

    @commands.command(name="growl", help="Let out a growl warning")
    async def growl_prefix(self, ctx):
        await ctx.send(random.choice(GROWLS))

    @app_commands.command(name="growl", description="Let out a growl warning", extras={"category": "general"})
    async def growl_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(random.choice(GROWLS), ephemeral=ephemeral)

    @commands.command(name="shift", help="Describe your wolf transformation")
    async def shift_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(SHIFTS)))

    @app_commands.command(name="shift", description="Describe your wolf transformation", extras={"category": "general"})
    async def shift_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(SHIFTS)), ephemeral=ephemeral)

    @commands.command(name="lonewolf", help="Embrace the lone wolf spirit")
    async def lonewolf_prefix(self, ctx):
        await ctx.send(wolf_wrap(random.choice(LONE_WOLF)))

    @app_commands.command(name="lonewolf", description="Embrace the lone wolf spirit", extras={"category": "general"})
    async def lonewolf_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(wolf_wrap(random.choice(LONE_WOLF)), ephemeral=ephemeral)

    @commands.command(name="wag", help="The bot wags its tail")
    async def wag_prefix(self, ctx):
        await ctx.send("🐺 *wags tail, near-crimson streaks catching the light*")

    @app_commands.command(name="wag", description="The bot wags its tail", extras={"category": "general"})
    async def wag_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message("🐺 *wags tail, near-crimson streaks catching the light*", ephemeral=ephemeral)

    @commands.command(name="moodtail", help="Bot wags its tail based on your mood")
    async def moodtail_prefix(self, ctx, *, mood: str = "happy"):
        response = MOODTAIL_RESPONSES.get(mood.lower(), "🐺 *tail shifts uncertainly* That mood isn't in the pack's vocabulary yet.")
        await ctx.send(response)

    @app_commands.command(name="moodtail", description="Bot wags its tail based on your mood", extras={"category": "general"})
    async def moodtail_slash(self, interaction: discord.Interaction, mood: str = "happy", ephemeral: bool = False):
        response = MOODTAIL_RESPONSES.get(mood.lower(), "🐺 *tail shifts uncertainly* That mood isn't in the pack's vocabulary yet.")
        await interaction.response.send_message(response, ephemeral=ephemeral)

    @commands.command(name="moonhowl", help="Howl according to the current moon phase")
    async def moonhowl_prefix(self, ctx):
        await ctx.send(embed=self._moonhowl_embed())

    @app_commands.command(name="moonhowl", description="Howl according to the current moon phase", extras={"category": "general"})
    async def moonhowl_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._moonhowl_embed(), ephemeral=ephemeral)

    def _moonhowl_embed(self) -> discord.Embed:
        import ephem
        from datetime import datetime
        moon = ephem.Moon()
        moon.compute(datetime.utcnow())
        phase = moon.phase
        if phase < 1:
            title = "🌑 New Moon Howl"
            desc = "Silence. The pack howls into the void — only those bonded can hear it."
        elif phase < 25:
            title = "🌒 Waxing Crescent Howl"
            desc = "A soft rising howl. Pack Resonance stirs at the edges. Something is building."
        elif phase < 50:
            title = "🌓 First Quarter Howl"
            desc = "Steady and controlled. Scout Alpha marks the halfway point with quiet authority."
        elif phase < 75:
            title = "🌔 Waxing Gibbous Howl"
            desc = "The howl grows. Near-crimson streaks catch more light with each passing night."
        elif phase < 99:
            title = "🌖 Waning Gibbous Howl"
            desc = "Deep and resonant. The peak has passed. The pack carries what was built."
        else:
            title = "🌕 Full Moon Howl"
            desc = "AWOOOOOOOO! The sigil pulses. Kael answers. Every bonded wolf in range feels it."
        embed = discord.Embed(title=title, description=desc, color=config.BOT_COLOR)
        embed.add_field(name="Illumination", value=f"{phase:.1f}%", inline=True)
        embed.set_footer(text="The moon commands. The pack obeys.")
        return embed

    @commands.command(name="musicpicks", help="Show Wolfy's Music Picks")
    async def musicpicks_prefix(self, ctx):
        await ctx.send(embed=self._musicpicks_embed())

    @app_commands.command(name="musicpicks", description="Show Wolfy's Music Picks", extras={"category": "general"})
    async def musicpicks_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._musicpicks_embed(), ephemeral=ephemeral)

    def _musicpicks_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎵 Wolfy's Music Picks", color=config.BOT_COLOR)
        embed.description = "\n".join(MUSIC_PICKS)
        embed.set_footer(text="Handpicked by the Alpha.")
        return embed

    @commands.command(name="fursona", help="Get or create a wolf fursona")
    async def fursona_prefix(self, ctx):
        await ctx.send(embed=self._fursona_embed(ctx.author))

    @app_commands.command(name="fursona", description="Get or create a wolf fursona", extras={"category": "general"})
    async def fursona_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._fursona_embed(interaction.user), ephemeral=ephemeral)

    def _fursona_embed(self, user: discord.User | discord.Member) -> discord.Embed:
        embed = discord.Embed(title=f"🐺 {user.display_name}'s Wolf Fursona", color=config.BOT_COLOR)

        if user.id == OWNER_ID:
            embed.add_field(name="Name", value="Wolfy", inline=True)
            embed.add_field(name="Role", value="Scout Alpha", inline=True)
            embed.add_field(name="Coat", value="Charcoal black with silver-grey undertone and near-crimson streaks", inline=True)
            embed.add_field(name="Eyes", value="Deep near-crimson", inline=True)
            embed.add_field(name="Trait", value="Fiercely loyal, protective to the core. Control over power. Always.", inline=False)
            embed.add_field(name="Sigil", value="Wolf-paw on right front shoulder — pulses slowly under intent or Pack Resonance.", inline=False)
        else:
            random.seed(user.id)
            name = random.choice(FURSONA_NAMES)
            coat = random.choice(FURSONA_COATS)
            eyes = random.choice(FURSONA_EYES)
            trait = random.choice(FURSONA_TRAITS)
            role = random.choice(FURSONA_ROLES)
            random.seed()
            embed.add_field(name="Name", value=name, inline=True)
            embed.add_field(name="Role", value=role, inline=True)
            embed.add_field(name="Coat", value=coat.capitalize(), inline=True)
            embed.add_field(name="Eyes", value=eyes.capitalize(), inline=True)
            embed.add_field(name="Trait", value=trait.capitalize(), inline=False)

        embed.set_footer(text="Seeded to your Discord ID — your fursona is yours permanently.")
        return embed

    @commands.command(name="wolfpackstats", help="Show server/pack stats")
    async def wolfpackstats_prefix(self, ctx):
        await ctx.send(embed=self._wolfpackstats_embed(ctx.guild))

    @app_commands.command(name="wolfpackstats", description="Show server/pack stats", extras={"category": "general"})
    async def wolfpackstats_slash(self, interaction: discord.Interaction, ephemeral: bool = False):
        await interaction.response.send_message(embed=self._wolfpackstats_embed(interaction.guild), ephemeral=ephemeral)

    def _wolfpackstats_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(title="🐺 Wolf Pack Stats", color=config.BOT_COLOR)
        if guild:
            online = sum(
                1 for m in guild.members
                if m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)
            )
            embed.add_field(name="Pack Size", value=str(guild.member_count), inline=True)
            embed.add_field(name="Online", value=str(online), inline=True)
            embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
            embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
            embed.add_field(name="Server Name", value=guild.name, inline=True)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
        else:
            embed.description = wolf_wrap("Pack stats only available in a server.")
        embed.set_footer(text="The pack endures.")
        return embed


async def setup(bot):
    await bot.add_cog(WolfLore(bot))
