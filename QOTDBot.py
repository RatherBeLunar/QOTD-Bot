#from flask import Flask, request, make_response, Response
import os
import time
import re
import json
import random

from WellBehavedSlackClient import *

from QuestionKeeper import *
from ScoreKeeper import *
from PollKeeper import *

# instantiate Slack client
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')

slack_client = None

questionKeeper = None
scoreKeeper = None
commandKeeper = None
pollKeeper = None

# starterbot's user ID in Slack: value is assigned after the bot starts up
bot_id = "UNKNOWN"

###app = Flask(__name__)

# constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
HELP_COMMAND = "help"
MENTION_REGEX = "^<@(|[WU].+?)>(.*)"
DEBUG_CHANNEL = "G9DHWHZP1"
TEST_CHANNEL = "C9DBNUYNL"
QOTD_CHANNEL = "C61L4NENS"
POINT_ANNOUNCEMENT_CHANNEL = "CA7DKN1DM"

DEVELOPER_ID = "U88LK3JN9" #Dana

DEPLOY_CHANNEL = QOTD_CHANNEL

LOG_FILE = "log.txt"
USER_LIST_FILE = "userList.json"

POINT_RESPONSES = ["Correct! I'll give you a point", ":thumbsup:", "Correct! :fast_parrot:"]


#Commands stuff
#----------------------------------

#Use this to post a message to a channel
def say(channel, response):
    try:
        slack_client.api_call(
            "chat.postMessage",
            channel=channel,
            text=response,
            icon_emoji=':robot_face:'
        )
        log("QOTD Bot says: " + (response if response else "[BLANK MESSAGE]") + "\n")
    except ValueError:
        log("QOTD Bot failed to say: " + (response if response else "[BLANK MESSAGE]") + "\n")

def react(channel, timestamp, emoji):
    try:
        slack_client.api_call(
            "reactions.add",
            channel = channel,
            timestamp = timestamp,
            name = emoji
        )
        log("QOTD Bot reacts with: " + (emoji if emoji else "[NO EMOJI]") + "\n")
    except ValueError:
        log("QOTD Bot failed to react with: " + (emoji if emoji else "[NO EMOJI]") + "\n")

def log(response):
    file = open(LOG_FILE, "a", newline='', encoding='utf8')
    file.write(response)
    file.close()
    print(response)

def getNameByID(userID):
    usersDict = {}

    #All Slack user IDs start with "U", by convention
    #So this is an easy check for invalid names
    if not userID.startswith('U'):
        return userID

    #Our top priority is to get the name from the score sheet,
    #since we can change that to a person's preference if they don't want to use their display name
    nameFromScoreSheet = scoreKeeper.getUserNameInScoreSheet(userID)
    if nameFromScoreSheet:
        userName = nameFromScoreSheet
        return userName

    #Next highest priority is to use the bulk list of all users we can manually pull from Slack
    with open(USER_LIST_FILE) as usersFile:
        usersDict = json.load(usersFile)
    if userID in usersDict:
        userName = usersDict[userID]
        return userName
    
    #Last ditch effort is to do an api call, which we really want to avoid
    attemptedNameJson = slack_client.api_call(
        "users.info",
        token = SLACK_BOT_TOKEN,
        user = userID
    )
    if attemptedNameJson["ok"]:
        if attemptedNameJson["user"]["profile"]["display_name"] != "":
            userName = attemptedNameJson["user"]["profile"]["display_name"]
        else:
            userName = attemptedNameJson["user"]["profile"]["real_name"]
    else:
        userName = userID

    return userName

def getReferenceByID(userID):
    return "<@" + userID + ">"

def getIDFromReference(userIDReference):
    for char in "<>@":
        userIDReference = userIDReference.replace(char, "")
    userID = userIDReference.strip()
    return userID



def getDirectChannel(userID):
    dmChannel = slack_client.api_call(
        "conversations.open",
        users = userID
    )

    return dmChannel["channel"]["id"]

def checkPublic(messageEvent):
    if not is_event_private(messageEvent):
        return "You can't use this command in a public channel. Message me directly instead"
    else:
        return ""

def checkPrivate(messageEvent):
    if is_event_private(messageEvent):
        return "You can't use this command in a private channel. Use the public channel instead"
    else:
        return ""

def needsMoreArgs(channel):
    say(channel, "This command needs more arguments! Type \"(command) help\" for usage")

def scores(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)
    response = ""

    #If a user to get scores for is specified
    if len(args) > 0 and args[0] != "":
        scoresForUser = getIDFromReference(args[0])
        
        if getNameByID(scoresForUser) != scoresForUser: #if user name is valid
            response = scoreKeeper.getUserScores(scoresForUser)
        else:
            response = "I couldn't find that user. Use `scores help` for usage instructions"
        
        say(channel, response)
        return

    #Otherwise, print scores for everyone
    response = scoreKeeper.getTodayScoresRanked()
    response += scoreKeeper.getTotalScoresRanked()
    say(channel, response)

def scoresUnranked(channel, userID, argsString, timestamp):
    response = scoreKeeper.getTodayScores()
    response += scoreKeeper.getTotalScores()
    say(channel, response)

def question(channel, userID, argsString, timestamp):
    if argsString == "":
        needsMoreArgs(channel)
        return

    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    response = ""

    if identifier == "remove":
        response = "You probably meant to use `question [identifier] remove`\n"
        say(channel, response)
        return
    
    if len(args) < 2:
        needsMoreArgs(channel)
        return
    args = args[1] #no longer holding identifier
    colonIndex = args.rfind(":")
    if colonIndex == -1:
        question = args.strip()
        answer = ""
    else:
        question = args[:colonIndex].strip()
        answer = args[colonIndex+1:].strip()

    if question == "remove":
        if questionKeeper.removeQuestion(identifier, "DEV" if userID == DEVELOPER_ID else userID):
            response = "Okay, I removed that question"
            say(channel, response)
            return
        else:
            response = "I couldn't find a question of yours with that ID"
            say(channel, response) 
            return

    if question == "count":
        q = questionKeeper.getUserQuestionByID(identifier, "DEV" if userID == DEVELOPER_ID else userID)

        if q is None:
            response = "I couldn't find a question of yours with that ID"
            say(channel, response)
            return

        numAnswers = q.countAnswers()
        numGuesses = q.countGuesses()

        response = str(numAnswers) + (" people" if numAnswers != 1 else " person") + " answered question " + q.qID + " correctly"

        if numAnswers > 0:
            response += ":\n"
            response += "\n".join([("-" + getNameByID(answeredByID)) for answeredByID in q.answeredBy])

        response += "\n\n"
        response += str(numGuesses) + (" people" if numGuesses != 1 else " person") + " guessed " + q.qID \
                 + ", and " + str(numGuesses - numAnswers) + " didn't guess the right answer"

        if (numGuesses - numAnswers) > 0:
            response += ":\n"
            response += "\n".join([("-" + getNameByID(guessedID)) for guessedID in q.guesses.keys() if guessedID not in q.answeredBy])

        say(channel, response)
        return


    #only get here if a valid question input format is given
    questionAdded = questionKeeper.addQuestion(userID = userID, qID = identifier, questionText = question, correctAnswer = answer)
    
    if questionAdded:
        response = "Okay, I added your question with ID " + identifier + ".\n"\
                 + "Use `publish` to make your questions publicly available, "\
                 + "or `question " + identifier + " remove` to remove it"
        say(channel, response)
        if answer == "":
            say(channel, "Warning: Your question doesn't seem to have a correct answer. Make sure this is intended before publishing.")
    else:
        response = "A question with this ID already exists right now. Please use a different one"
        say(channel, response)

def questions(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)
    
    if is_channel_private(channel):
        response = questionKeeper.listQuestionsPrivate(userID)
    else:
        response = questionKeeper.listQuestions()
    
    if response == "":
        response = "There are no currently active questions"
    else:
        response = "Here are all the currently active questions:\n" + response
    
    say(channel, response)

def removeQuestion(channel, userID, argsString, timestamp):
    if argsString == "":
        needsMoreArgs(channel)
        return

    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    question(channel, userID, identifier + " remove", timestamp)


def myQuestions(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)
    
    response = questionKeeper.listQuestionsByUser(userID)

    if response == "":
        response = "You have no questions right now. Use `question` to add some"
    else:
        response = "Here are all of your questions:\n" + response
    
    say(channel, response)

def publish(channel, userID, argsString, timestamp):

    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    if identifier != "":
        publishResponse = questionKeeper.publishByID(identifier)
        if publishResponse == "published":
            response = "Okay, I published question " + identifier + ".\n"
        elif publishResponse == "already published":
            response = identifier + " is already published.\n"
        else:
            response = "I couldn't find a question with that ID.\n"
    else:
        questionKeeper.publishAllByUser(userID)
        response = "Okay, I've published all of your questions\n"

    newQuestions = questionKeeper.firstTimeDisplay()
    if newQuestions != "":
        say(DEPLOY_CHANNEL, "New questions:\n" + newQuestions)

    say(channel, response)
    
def answer(channel, userID, argsString, timestamp):

    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    if len(args) < 2:
        needsMoreArgs(channel)
        return
    
    inputAnswer = args[1] #no longer holding identifier
    checkResponse = questionKeeper.checkAnswer(userID, identifier, inputAnswer)

    if checkResponse == "correct":
        qID = questionKeeper.getQuestionByID(identifier).qID #Calling this to get proper capitalization
        response = random.choice(POINT_RESPONSES) + "\n"

        if not scoreKeeper.userExists(userID):
            scoreKeeper.addNewUser(userID)
            scoreKeeper.addNameToUser(userID, getNameByID(userID))

        scoreKeeper.addUserPoint(userID)
        say(POINT_ANNOUNCEMENT_CHANNEL, "Point for " + getNameByID(userID) + ((" on question " + qID + "!") if qID != "" else "!") \
                            + ("\nThough they are the one who submitted it :wha:..." if userID == questionKeeper.getSubmitterByQID(qID) else ""))

    elif checkResponse == "incorrect":
        q = questionKeeper.getQuestionByID(identifier)
        guessesLeft = MAX_GUESSES - q.guesses[userID]
        response = "Incorrect. You have " + str(guessesLeft) + (" guesses left.\n" if guessesLeft != 1 else " guess left.\n")
        if guessesLeft == 0:
            response += "The correct answer was \"" + q.correctAnswer + "\". If you think your guess(es) should have been correct, contact " \
                     +  getReferenceByID(q.userID) + ", who submitted the question.\n" 

    elif checkResponse == "already answered":
        response = "You already answered that question!"

    elif checkResponse == "max guesses":
        response = "You've already guessed the maximum number of times, " + str(MAX_GUESSES) + "."

    elif checkResponse == "needsManual":
        userWhoSubmitted = questionKeeper.getSubmitterByQID(identifier)
        response = "This question needs to be validated manually. I'll ask " + getNameByID(userWhoSubmitted) + " to check your answer."
        directUserChannel = getDirectChannel(userWhoSubmitted)
        say(directUserChannel, getNameByID(userID) + " has answered \"" + inputAnswer + "\" for your question,\n" + questionKeeper.getQuestionByID(identifier).prettyPrint() \
            + "\nIs this correct?\n(I don't know how to validate answers this way yet)")
    else:
        response = "I couldn't find a question with that ID.\n Use `questions` to find the proper ID.\n"

    say(channel, response)

def oldQuestions(channel, userID, argsString, timestamp):
    response = questionKeeper.getOldQuestionsString()

    if response != "":
        response = "Here are all of the questions I found that were expired in the last 24 hours:\n\n" + response
    else:
        response = "I couldn't find any questions that were expired in the last 24 hours"
    say(channel, response)
    

def hello(channel, userID, argsString, timestamp):

    response = "Hello " + getNameByID(userID) + ", I'm QOTD Bot!"
    response += "\nYour User ID is: " + userID + "\nThis channel's ID is: " + channel + "\nUse the `help` command for usage instructions.\n"
    
    say(channel, response)


def addPoints(channel, userID, argsString, timestamp):
    args = argsString.split(' ')

    if len(args) < 1 or args[0] == "":
        needsMoreArgs(channel)
        return

    pointsForUser = getIDFromReference(args[0])
    numPoints = args[1] if len(args) >= 2 and args[1] != "" else "1"

    if getNameByID(pointsForUser) == pointsForUser: #if user name is invalid
        say(channel, "I couldn't find that user. Use `add-point help` for usage instructions")
        return
    
    #Get a string of just digits
    numPointsDigitsOnly = "".join([c for c in numPoints if c.isdigit()])
    #Add back in a negative sign if one was given
    if numPoints != "" and numPoints[0] == "-" and numPointsDigitsOnly != "":
        numPointsDigitsOnly = "-" + numPointsDigitsOnly

    if numPointsDigitsOnly == "":
        say(channel, "I couldn't interpret " + numPoints + " as a number. Try again\n")
        return

    if not scoreKeeper.userExists(userID):
        scoreKeeper.addNewUser(userID)
        scoreKeeper.addNameToUser(userID, getNameByID(userID))

    numPointsDigitsOnly = int(numPointsDigitsOnly)
    scoreKeeper.addUserPoints(pointsForUser, numPointsDigitsOnly)

    response = "Okay, I gave " + str(numPointsDigitsOnly) + " point" + ("s" if numPointsDigitsOnly != 1 else "") + " to " + getNameByID(pointsForUser)
    say(DEPLOY_CHANNEL, response)

def expireOldQuestions(channel, userID, argsString, timestamp):

    expiredQuestions = questionKeeper.expireQuestions(userID)
    expiredQuestionsStrings = []
    for q in expiredQuestions:
        expiredQuestionsStrings.append(q.prettyPrintWithAnswer())
        if len(q.getAnsweredUsers()) > 0:
            expiredQuestionsStrings.append("    Answered by:")
        for answeredUserID in q.getAnsweredUsers():
            expiredQuestionsStrings.append("        -" + getNameByID(answeredUserID))
        expiredQuestionsStrings.append("\n")

    if len(expiredQuestions) > 0:
        response = "The following questions have expired:\n"
        response += '\n'.join(expiredQuestionsStrings)
        if channel != DEPLOY_CHANNEL:
            say(DEPLOY_CHANNEL, response)
    else:
        response = "No questions of yours older than 18 hours were found"

    say(channel, response)


def poll(channel, userID, argsString, timestamp):
    if argsString == "":
        needsMoreArgs(channel)
        return

    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    response = ""

    if identifier == "remove":
        response = "You probably meant to use `poll [identifier] remove`\n"
        say(channel, response)
        return

    if len(args) < 2:
        needsMoreArgs(channel)
        return
    
    args = args[1].split(" : ") #no longer holding identifier, question and options split
    question = args[0]
    optionsList = args[1:]

    optionsDict = {}
    for i in range(len(optionsList)):
        optionsDict[str(i+1)] = optionsList[i]
    
    if question == "remove":
        if pollKeeper.removePoll(identifier, "DEV" if userID == DEVELOPER_ID else userID):
            response = "Okay, I removed that poll"
            say(channel, response)
            return
        else:
            response = "I couldn't find a poll of yours with that ID"
            say(channel, response) 
            return

    if question in ["votes", "status", "results", "check"]:
        response = pollKeeper.displayResults(identifier)
        if response is None:
            response = "I couldn't find a poll with that ID"
        say(channel, response) 
        return



    #only get here if a valid poll input format is given
    pollAdded = pollKeeper.addPoll(userID = userID, pID = identifier, pollQuestionText = question, options = optionsDict)
    
    if pollAdded:
        response = "Okay, I added your poll with ID " + identifier + ".\n"\
                 + "It looks like this:\n\n\n" + pollKeeper.getPollByID(identifier).prettyPrint() + "\n\n\n"\
                 + "Use `publish-poll` to make your poll publicly available, "\
                 + "or `poll " + identifier + " remove` to remove it"
    else:
        response = "A poll with this ID already exists right now. Please use a different one"

    say(channel, response)

def polls(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)
    
    response = pollKeeper.listPolls()
    
    if response == "":
        response = "There are no currently active polls"
    else:
        response = "Here are all the currently active polls:\n" + response
    
    say(channel, response)

def publishPoll(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    if identifier != "":
        publishResponse = pollKeeper.publishByID(identifier)
        if publishResponse == "published":
            response = "Okay, I published poll " + identifier + ".\n"
        elif publishResponse == "already published":
            response = identifier + " is already published.\n"
        else:
            response = "I couldn't find a poll with that ID.\n"
    else:
        pollKeeper.publishAllByUser(userID)
        response = "Okay, I've published all of your polls\n"

    newPolls = pollKeeper.firstTimeDisplay()
    if newPolls != "":
        say(DEPLOY_CHANNEL, "New polls:\n" + newPolls)

    say(channel, response)

def respondToPoll(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)
    identifier = args[0] if len(args) > 0 else ""

    if len(args) < 2:
        needsMoreArgs(channel)
        return
    
    inputVote = args[1] #no longer holding identifier
    checkVote = pollKeeper.submitResponse(userID, identifier, inputVote)

    if checkVote == "not found":
        response = "I couldn't find a poll with that ID.\n"
        say(channel, response)
        return

    if checkVote == "bad vote":
        response = "I couldn't find an option that matches \"" + identifier + "\".\n"
        say(channel, response)
        return
    
    react(channel, timestamp, "thumbsup")

def tell(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)

    response = ""

    if len(args) < 2:
        #Not using the needsMoreArgs function since this is a hidden command and has no help text
        say(channel, "this command needs more arguments!")
        return
   
    userToTell = getIDFromReference(args[0])
    whatToSay = args[1]

    if getNameByID(userToTell) == userToTell: #if user name is invalid
        say(channel, "I couldn't find that user. Use `add-point help` for usage instructions")
        return

    say(DEPLOY_CHANNEL, "Hey " + getReferenceByID(userID) + ", " + getReferenceByID(userID) + " says " + whatToSay)

def devTell(channel, userID, argsString, timestamp):
    args = argsString.split(' ', 1)

    response = ""

    if len(args) < 2:
        #Not using the needsMoreArgs function since this is a hidden command and has no help text
        say(channel, "this command needs more arguments!")
        return
   
    userToTell = getIDFromReference(args[0])
    whatToSay = args[1]

    if getNameByID(userToTell) == userToTell: #if user name is invalid
        say(channel, "I couldn't find that user. Use `add-point help` for usage instructions")
        return

    userChannel = getDirectChannel(userToTell)

    say(userChannel, whatToSay)

def announce(channel, userID, argsString, timestamp):
    say(DEPLOY_CHANNEL, argsString)

def refreshUserList(channel, userID, argsString, timestamp):
    usersJson = {}

    usersList = slack_client.api_call("users.list")["members"]
    for member in usersList:
        name = member["profile"]["display_name"]
        if name == "":
            name = member["profile"]["real_name"]
        usersJson[member["id"]] = name

    tempfile = NamedTemporaryFile(delete=False)
    with open(USER_LIST_FILE, 'w') as tempfile:
        json.dump(usersJson, tempfile, indent = 4)

    shutil.move(tempfile.name, USER_LIST_FILE)


class Command:
    def __init__(self, aliases, func, category = "", helpText = "", publicOnly = False, privateOnly = False, devOnly = False):
        self.aliases = aliases
        self.func = func
        self.category = category
        self.helpText = helpText
        self.publicOnly = publicOnly
        self.privateOnly = privateOnly
        self.devOnly = devOnly
        

class CommandKeeper:
    def __init__(self):
        self.helpTextDict = {"Misc" : []}
        self.commandsList = [
            Command(
                aliases = ["points","score","scores"],
                func = scores,
                category = "Scoring and Points",
                helpText = "`scores <@ user>` - prints a list of today's scores and running totals, for `<@ user>` if given, for everyone otherwise"
            ),
            
            Command(
                aliases = ["score-unranked","scores-unranked"],
                func = scoresUnranked,
                category = "Scoring and Points",
                helpText = "`scores-unranked` - prints a list of today's scores and running totals, sorted alphabetically instead of by ranking"
            ),
            
            Command(
                aliases = ["q","question"],
                func = question,
                category = "Questions and Answers",
                helpText = "`question [identifier] [question] : <answer>` - creates a question with a reference tag `identifier`.\n"\
                         + "`question [identifier] remove` - removes the question with the corresponding ID.\n"\
                         + "`question [identifier] count` - shows stats on who has answered/guessed a question.",
                privateOnly = True
            ),
            
            Command(
                aliases = ["qs","questions"],
                func = questions,
                
                category = "Questions and Answers",
                helpText = "`questions` - prints a list of today's published questions"
            ),

            Command(
                aliases = ["rq", "remove", "remove-question"],
                func = removeQuestion,
                category = "Questions and Answers",
                helpText = "`remove [identifier]` removes the question with the corresponding ID" 
            ),

            Command(
                aliases = ["my-questions"],
                func = myQuestions,
                category = "Questions and Answers",
                helpText = "`my-questions` - prints a list of your questions, published or not"
            ),

            Command(
                aliases = ["publish"],
                func = publish,
                category = "Questions and Answers",
                helpText = "`publish <identifier>` - publishes the corresponding question if `identifier` given. "\
                         + "Publishes all of your questions otherwise."
            ),

            Command(
                aliases = ["a","answer"],
                func = answer,
                category = "Questions and Answers",
                helpText = "`answer [identifier] [your answer]` - Must be used in a private channel. "\
                         + "Checks your `answer` for the corresponding question.",
                privateOnly = True
            ),

            Command(
                aliases = ["hi","hello","hola"],
                func = hello,
                helpText = "`hello` - says hi back and some basic information"
            ),

            Command(
                aliases = ["add-point","add-points"],
                func = addPoints,
                category = "Scoring and Points",
                helpText = "`add-point(s) [@ user] <# points>` "\
                         + "- gives `# points` to `@ user` if specified, 1 point by default",
                publicOnly = True
            ),

            Command(
                aliases = ["expire-old-questions"],
                func = expireOldQuestions,
                category = "Questions and Answers",
                helpText = "`expire-old-questions` - removes all questions published more than 18 hours ago"
            ),

            Command(
                aliases = ["old-questions", "expired-questions", "old-answers"],
                func = oldQuestions,
                category = "Questions and Answers",
                helpText = "`old-questions` - gets a list of questions that were expired in the last 24 hours"
            ),

            Command(
                aliases = ["tell", "say", "trash-talk"],
                func = tell
            ),

            Command(
                aliases = ["dev-say", "dev-tell", "dev-talk"],
                func = devTell,
                devOnly = True
            ),

            Command(
                aliases = ["announce"],
                func = announce,
                devOnly = True
            ),

            Command(
                aliases = ["refresh-user-list"],
                func = refreshUserList,
                devOnly = True
            ),

            Command(
                aliases = ["poll", "p"],
                func = poll,
                category = "Polls",
                helpText = "`poll [identifier] [question] : [option 1] : [option 2] : ...` - creates a poll with a reference tag `identifier`.\n"\
                         + "`poll [identifier] remove` - removes the poll with the corresponding ID.\n"\
                         + "`poll [identifier] votes` - shows current vote counts for a poll."
            ),

            Command(
                aliases = ["polls"],
                func = polls,
                category = "Polls",
                helpText = "`polls` - prints a list of the currently active polls"
            ),

            Command(
                aliases = ["publish-poll", "publish-polls"],
                func = publishPoll,
                category = "Polls",
                helpText = "`publish-poll [identifier]` - publishes your poll with the specified identifier"
            ),

            Command(
                aliases = ["respond", "poll-answer", "poll-respond", "answer-poll", "vote"],
                func = respondToPoll,
                category = "Polls",
                helpText = "`vote [identifier] [option-number]` - votes on a poll. Use option IDs, not the option's text"
            )
        ]

        for command in self.commandsList:
            if command.helpText == "":
                continue
            if command.category == "" or command.category == "Misc":
                self.helpTextDict["Misc"].append(command.helpText)
            elif command.category in self.helpTextDict.keys():
                self.helpTextDict[command.category].append(command.helpText)
            else:
                self.helpTextDict[command.category] = [command.helpText]
        for category in self.helpTextDict.keys():
            self.helpTextDict[category].sort()

    def help(self, channel):
        response = ""

        for category in self.helpTextDict:
            response += "*" + category + "*:\n"
            for helpText in self.helpTextDict[category]:
                for line in helpText.split("\n"):
                    response += "    " + line + "\n\n"
            response += "\n\n"
        response = response[:-2]

        say(channel, "Here's a list of commands I know:\n\n" + response)

    def getCommandByAlias(self, alias):
        for cmd in self.commandsList:
            if alias in cmd.aliases:
                return cmd
        return None

    def handle_event(self, event):
        """
            Executes bot command if the command is known
        """
        userID = event["user"]
        channel = event["channel"]
        if "ts" in event:
            timestamp = event["ts"]
        else:
            timestamp = time.time()

        #Clean up multiple whitespace characters for better uniformity for all commands
        #e.g. "This   is:       some text" turns into "This is: some text"
        event["text"] = " ".join(event["text"].split())

        splitArguments = event["text"].split(' ', 1)
        commandAlias = splitArguments[0].lower()

        #This is the result of @qotd_bot help
        if commandAlias == "help":
            self.help(channel)

        cmd = self.getCommandByAlias(commandAlias)
        if not cmd:
            #say(channel, "Invalid command")
            return

        if len(splitArguments) > 1:
            #This is the result of @qotd_bot [command] help
            if splitArguments[1] == "help":
                say(channel, cmd.helpText)
                return
            
            args = splitArguments[1] #slice off the command ID, leaving just arguments
        else:
            args = ""


        if cmd.devOnly and userID != DEVELOPER_ID:
            response = "I'm sorry, " + getReferenceByID(originUserID) + ", I'm afraid I can't let you do that."
            say(channel, response)
            return

        if cmd.publicOnly and is_channel_private(channel):
            say(channel, "You can't use this command in a private channel. Use the public channel instead")
            return

        if cmd.privateOnly and not is_channel_private(channel):
            say(channel, "You can't use this command in a public channel. Message me directly instead")
            return

        
        #If we make it through all the checks, we can actually run the corresponding function
        cmd.func(channel, userID, args, timestamp)


#----------------------------------

def is_channel_private(channel):
    return channel.startswith('D')

def is_event_private(messageEvent):
    """Checks if private slack channel"""
    return messageEvent['channel'].startswith('D')


def parse_bot_commands(slack_events):
    """
        Parses a list of events coming from the Slack RTM API to find bot commands.
        If a bot command is found, this function returns a tuple of command and channel.
        If its not found, then this function returns None, None.
    """
    for event in slack_events:
        if event["type"] == "goodbye":
            print("Got 'goodbye' message. Reconnecting now")
            slack_client.rtm_connect(with_team_state=False)
        if event["type"] == "error":
            print("Network error. Retrying in 5 seconds...\n")
            time.sleep(5)
            return None
        if event["type"] == "message" and not "subtype" in event:
            processedEvent = parse_direct_mention(event)
            if processedEvent:
                log(getNameByID(event["user"]) + " says: " + event["text"] + "\n")
                return processedEvent
    return None

def parse_direct_mention(event):
    message_text = event["text"]
    """
        Finds a direct mention (a mention that is at the beginning) in message text
        and returns the user ID which was mentioned. If there is no direct mention, returns None
    """
    matches = re.search(MENTION_REGEX, message_text)
    # the first group contains the username, the second group contains the remaining message
    #If direct mention...
    if matches and matches.group(1) == bot_id:
        event["text"] = matches.group(2).strip()
        #return (matches.group(1), matches.group(2).strip())
        return event
    #If private message (no mention necessary)
    elif is_event_private(event):
        #return (bot_id, message_text)
        return event
    else:
        return None





if __name__ == "__main__":
    slack_client = WellBehavedSlackClient(SLACK_BOT_TOKEN)

    if slack_client.rtm_connect(with_team_state=False):
        
        questionKeeper = QuestionKeeper()
        scoreKeeper = ScoreKeeper()
        commandKeeper = CommandKeeper()
        pollKeeper = PollKeeper()

        print("QOTD Bot connected and running!")
        # Read bot's user ID by calling Web API method `auth.test`
        bot_id = slack_client.api_call("auth.test")["user_id"]
        while True:
            #command, channel = parse_bot_commands(slack_client.rtm_read())
            try:
                event = parse_bot_commands(slack_client.rtm_read())
            except BaseException as e:
                log("Connection Error. Retrying in 3 seconds...")
                log("Exception details: " + str(e))
                time.sleep(3)
                try:
                    slack_client.rtm_connect(with_team_state=False)
                except BaseException as e:
                    log("Couldn't reconnect :(")
                    log("Exception details: " + str(e))
                    continue
                continue
            #if command:
            if event:
               commandKeeper.handle_event(event)
            time.sleep(RTM_READ_DELAY)
    else:
        print("Connection failed. Exception traceback printed above.")