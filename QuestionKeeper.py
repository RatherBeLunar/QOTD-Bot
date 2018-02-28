import time
import json
from tempfile import NamedTemporaryFile
import shutil

MAX_GUESSES = 3

QUESTIONS_FILE_NAME = "questions.json"

class Question:
    def __init__(self, userID, qID, questionText, correctAnswer = ""):
        self.userID = userID
        self.qID = qID
        self.questionText = questionText
        self.correctAnswer = correctAnswer
        self.initTime = time.time()
        self.publishTime = 0
        self.published = False
        self.justPublished = False
        self.answeredBy = []
        self.guesses = {}
        
    def cleanUpAnswer(self, answer):
        answer = answer.lower().strip()
        words = answer.split(' ')
        removeWords = ["a","an","the"]

        strippedWords = [word for word in words if word not in removeWords]
        answer = ' '.join(strippedWords).strip()
        return answer

    def checkAnswer(self, userID, inputAnswer):
        match = self.cleanUpAnswer(self.correctAnswer) == self.cleanUpAnswer(inputAnswer)
        if match and userID not in self.answeredBy:
            self.answeredBy.append(userID)
        return match

    def timeToExpire(self):
        return (time.time() - self.publishTime) > 60 * 60 * 18

    def prettyPrint(self):
        return "(" + self.qID + "): " + self.questionText

    def prettyPrintWithAnswer(self):
        return "(" + self.qID + "): " + self.questionText + " : " + self.correctAnswer

    def publish(self):
        if self.published:
            return False
        else:
            self.published = True
            self.justPublished = True
            self.publishTime = time.time()
            return True

class QuestionKeeper:
    def __init__(self):
        self.questionList = []
        self.loadQuestionsFromFile()

    def loadQuestionsFromFile(self):
        with open(QUESTIONS_FILE_NAME) as qFile:
            d = json.load(qFile)
            for qJson in d["questions"]:
                q = Question(qJson["userID"], qJson["qID"], qJson["questionText"], qJson["correctAnswer"])
                q.initTime = qJson["initTime"]
                q.publishTime = qJson["publishTime"]
                q.published = qJson["published"]
                q.justPublished = qJson["justPublished"]
                q.answeredBy = qJson["answeredBy"]
                q.guesses = qJson["guesses"]

                self.questionList.append(q)
            

    def writeQuestionsToFile(self):
        questionsJson = {"questions" : []}

        for q in self.questionList:
            questionsJson["questions"].append(vars(q))

        tempfile = NamedTemporaryFile(delete=False)
        with open(QUESTIONS_FILE_NAME, 'w') as tempfile:
            json.dump(questionsJson, tempfile, indent = 4)

        shutil.move(tempfile.name, QUESTIONS_FILE_NAME)

    def addQuestion(self, userID, qID, questionText, correctAnswer = ""):
        for q in self.questionList:
            if qID.lower() == q.qID.lower():
                return False
        
        self.questionList.append(Question(userID, qID, questionText, correctAnswer))

        #save new data
        self.writeQuestionsToFile()
        return True

    def removeQuestion(self, qID):
        for q in self.questionList:
            if qID.lower() == q.qID.lower():
                self.questionList.remove(q)
                
                #save new data
                self.writeQuestionsToFile()
                return True
        return False

    def getQuestionByID(self, qID):
        for q in self.questionList:
            if qID.lower() == q.qID.lower():
                return q

        return None

    def getSubmitterByQID(self, qID):
        q = self.getQuestionByID(qID)
        if q:
            return q.userID
        else:
            return None

    def checkAnswer(self, userID, qID, inputAnswer):
        q = self.getQuestionByID(qID)
        if q and q.published:
            if userID in q.answeredBy:
                return "already answered"

            if userID in q.guesses:
                q.guesses[userID] += 1
            else:
                q.guesses[userID] = 1


            if q.guesses[userID] >= MAX_GUESSES + 1:
                self.writeQuestionsToFile()
                return "max guesses"
            elif q.correctAnswer == "":
                self.writeQuestionsToFile()
                return "needsManual"
            elif q.checkAnswer(userID, inputAnswer):
                self.writeQuestionsToFile()
                return "correct"

            self.writeQuestionsToFile()
            return "incorrect"
        return "notFound"

    def listQuestions(self):
        output = ""
        for q in self.questionList:
            if q.published:
                output += q.prettyPrint() + "\n"
        return output

    def listQuestionsByUser(self, userID):
        output = ""
        for q in self.questionList:
            if q.userID == userID:
                output += q.prettyPrintWithAnswer() + (" (published)" if q.published else "") + "\n"
        return output

    def expireQuestions(self, userID):
        questionsExpired = []
        for q in self.questionList:
            if q.timeToExpire() and q.userID == userID:
                questionsExpired.append(q.prettyPrintWithAnswer())
                self.questionList.remove(q)
        self.writeQuestionsToFile()

        return questionsExpired

    def publishByID(self, qID):
        q = self.getQuestionByID(qID)
        if q:
            if q.publish():
                self.writeQuestionsToFile()
                return "published"
            else:
                return "already published"
        else:
            return "notFound"

    def publishAllByUser(self, userID):
        for q in self.questionList:
            if q.userID == userID:
                q.publish()
        self.writeQuestionsToFile()

    def firstTimeDisplay(self):
        output = ""
        for q in self.questionList:
            if q.justPublished:
                q.justPublished = False
                output += q.prettyPrint() + "\n"
        self.writeQuestionsToFile()
        return output



